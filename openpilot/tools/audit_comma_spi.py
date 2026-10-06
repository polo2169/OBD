#!/usr/bin/env python3
"""Offline SPI audit of cereal rlogs or saved passive transport observations.

No device, serial, CAN, network, or Params access. Cereal is needed only for
rlogs; add an openpilot checkout to PYTHONPATH when using that format.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

EPISODE_GAP_NS = 20_000_000
TRANSFER_CONTEXT = re.compile(r'^\s*(\d+) / (0x[0-9a-fA-F]+) / (\d+) / (\d+) / tx:')


def message_text(record):
  # Swaglog files type-tag scalar fields; cereal logMessage uses plain keys.
  value = record.get('msg', record.get('msg$s', ''))
  return value if isinstance(value, str) else ''


def summarize(logs, samples):
  logs = sorted(logs, key=lambda row: row['mono'])
  samples = sorted(samples, key=lambda row: row['mono'])
  errors = Counter()
  endpoints = Counter()
  groups = []
  for row in logs:
    text = row['message']
    if context := TRANSFER_CONTEXT.match(text):
      endpoints[context[2]] += 1
    if text.startswith('SPI:') or text.startswith('transfer failed,'):
      errors[text] += 1
    if text.startswith('SPI: got NACK,'):
      if not groups or row['mono'] - groups[-1][-1]['mono'] > EPISODE_GAP_NS:
        groups.append([])
      groups[-1].append(row)

  known_increase = 0
  discontinuities = []
  for before, after in zip(samples, samples[1:]):
    if after['spi'] < before['spi'] or after['uptime'] < before['uptime']:
      # Do not interpret a reboot or an ambiguous 16-bit rollover as errors.
      discontinuities.append({'before': before, 'after': after})
    else:
      known_increase += after['spi'] - before['spi']
  return {
    'spi_counter': {'first': samples[0] if samples else None, 'last': samples[-1] if samples else None,
                    'observed_increase_excluding_discontinuities': known_increase if samples else None,
                    'discontinuities': discontinuities},
    'transport_messages': dict(errors), 'transfer_contexts_by_endpoint': dict(endpoints),
    'nack_messages': sum(len(group) for group in groups),
    'nack_time_groups': [{'first_mono_ns': group[0]['mono'], 'last_mono_ns': group[-1]['mono'],
                         'nack_count': len(group), 'messages': [row['message'] for row in group]} for group in groups],
    'grouping_note': 'NACKs separated by at most 20 ms are grouped heuristically, not counted as proven independent hardware faults.',
    'counter_note': 'Panda counts failed checksum paths, including recovery traffic; VERSION enumeration also increments this firmware counter.',
    'limits': 'Absence of a final transfer error does not prove lossless CAN or validate physical steering.',
  }


def read_rlog(path):
  from cereal import log
  import capnp
  raw = path.read_bytes()
  if path.suffix == '.zst':
    import io
    import zstandard
    raw = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)).read()
  logs, samples = [], []
  events_read = 0
  parse_error = None
  services = Counter()
  invalid = Counter()
  first, last = {}, {}
  max_gap = Counter()
  try:
    for event in log.Event.read_multiple_bytes(raw):
      events_read += 1
      service = event.which()
      if service in ('can', 'pandaStates'):
        services[service] += 1
        invalid[service] += not event.valid
        first.setdefault(service, event.logMonoTime)
        if service in last:
          max_gap[service] = max(max_gap[service], event.logMonoTime-last[service])
        last[service] = event.logMonoTime
      if service == 'pandaStates':
        # This reference device has one internal Panda. Never mix counters
        # from multiple devices into a single diagnostic series.
        if len(event.pandaStates) != 1:
          raise ValueError('Exactly one Panda required for this audit')
        p = event.pandaStates[0]
        row = {'mono': event.logMonoTime, 'spi': p.spiErrorCount, 'uptime': p.uptime,
               'mode': str(p.safetyModel), 'voltage': p.voltage}
        # Keep endpoints and changes without thousands of duplicate samples.
        if not samples or row['spi'] != samples[-1]['spi'] or row['uptime'] < samples[-1]['uptime']:
          samples.append(row)
      elif service == 'logMessage':
        try:
          record = json.loads(event.logMessage)
        except ValueError:
          continue
        text = message_text(record)
        if record.get('filename', '').endswith('spi.cc') or text.startswith('SPI:'):
          logs.append({'mono': event.logMonoTime, 'message': text, 'level': record.get('levelnum')})
  except capnp.KjException as exc:
    # Power loss may leave a partial event: keep earlier evidence and disclose
    # where decoding stopped instead of declaring the whole file healthy.
    parse_error = str(exc).split('stack:')[0].strip()
  return logs, samples, {
    'events_decoded': events_read, 'parse_error': parse_error,
    'services': {name: {'messages': count, 'invalid_messages': invalid[name],
                        'duration_s': (last[name]-first[name])/1e9,
                        'max_publication_gap_ms': max_gap[name]/1e6} for name, count in services.items()},
  }


def audit(path):
  if path.suffix == '.json':
    data = json.loads(path.read_text())
    logs = data['logs']
    samples = data.get('spi_changes', data.get('samples', []))
    metadata = {'services': None, 'parse_error': data.get('trailing_parse_error'),
                'note': 'Saved filtered observation: absence of messages outside this selection is not verified.'}
  else:
    logs, samples, metadata = read_rlog(path)
  return {'source': str(path), 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
          **metadata, **summarize(logs, samples)}


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('inputs', type=Path, nargs='+')
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  if args.output.resolve() in {path.resolve() for path in args.inputs}:
    parser.error('Output must not replace an input capture')
  reports = [audit(path) for path in args.inputs]
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(json.dumps(reports, indent=2)+'\n')
  for report in reports:
    print(f"{report['source']}: {report['nack_messages']} NACKs, "
          f"{len(report['nack_time_groups'])} time groups; partial={bool(report['parse_error'])}")


if __name__ == '__main__':
  main()
