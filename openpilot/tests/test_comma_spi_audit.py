from tools.audit_comma_spi import message_text, summarize


def test_native_and_typed_logs_have_the_same_message():
  text = 'SPI: got NACK, waiting for 0x85'
  assert message_text({'msg': text}) == message_text({'msg$s': text}) == text
  assert message_text({'msg': {'event$s': 'unrelated'}}) == ''


def test_counter_recovery_traffic_is_not_equated_to_distinct_nacks():
  logs = [
    {'mono': 1_000_000_000, 'message': 'SPI: got NACK, waiting for 0x85'},
    {'mono': 1_000_100_000, 'message': '  41 / 0x81 / 0 / 1984 / tx: '},
    {'mono': 1_001_000_000, 'message': 'SPI: got NACK, waiting for 0x79'},
    {'mono': 2_000_000_000, 'message': 'SPI: got NACK, waiting for 0x85'},
  ]
  samples = [{'mono': 900_000_000, 'spi': 10, 'uptime': 5},
             {'mono': 2_100_000_000, 'spi': 20, 'uptime': 6}]
  result = summarize(logs, samples)
  assert result['nack_messages'] == 3
  assert len(result['nack_time_groups']) == 2
  assert result['spi_counter']['observed_increase_excluding_discontinuities'] == 10
  assert result['transfer_contexts_by_endpoint'] == {'0x81': 1}


def test_reset_or_ambiguous_rollover_does_not_become_a_huge_error_count():
  samples = [{'mono': 1, 'spi': 65534, 'uptime': 100},
             {'mono': 2, 'spi': 3, 'uptime': 101},
             {'mono': 3, 'spi': 1, 'uptime': 1},
             {'mono': 4, 'spi': 6, 'uptime': 2}]
  result = summarize([], samples)
  assert len(result['spi_counter']['discontinuities']) == 2
  assert result['spi_counter']['observed_increase_excluding_discontinuities'] == 5


def test_no_observation_is_not_a_zero_error_measurement():
  assert summarize([], [])['spi_counter']['observed_increase_excluding_discontinuities'] is None
