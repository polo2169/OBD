// Offline-only adapter exposing the unmodified reference fork's C test library.
// Build with -I <exact reference opendbc root>; never link into a vehicle image.
#include "opendbc/safety/tests/libsafety/safety.c"

unsigned int audit_rx_len(void) { return current_safety_config.rx_checks_len; }
unsigned int audit_rx_field(unsigned int i, unsigned int field) {
  const RxCheck *r = &current_safety_config.rx_checks[i];
  unsigned int n = r->status.index;
  switch (field) {
    case 0: return r->msg[n].addr;
    case 1: return r->msg[n].bus;
    case 2: return r->msg[n].len;
    case 3: return r->msg[n].frequency;
    case 4: return r->status.msg_seen;
    case 5: return r->status.lagging;
    case 6: return r->status.valid_checksum;
    case 7: return r->status.wrong_counters;
    default: return 0;
  }
}
unsigned int audit_received_checksum(const CANPacket_t *p) { return psa_get_checksum(p); }
unsigned int audit_computed_checksum(const CANPacket_t *p) { return psa_compute_checksum(p); }
unsigned int audit_counter(const CANPacket_t *p) { return psa_get_counter(p); }
