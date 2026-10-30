#include "base.h"
#include "avrisp_mkii.c"

/* Timed 115200-baud UART with the real PIC24 four-character RX FIFO. */
static uint8_t incoming[300], fifo[4], expected[266];
static unsigned incoming_len, incoming_pos, fifo_head, fifo_count;
static unsigned now, next_arrival=10, overflows, commands, entry_baud;
static bool overrun;
volatile uint8_t usb_device_state;

static void advance(unsigned us) {
  while (us--) {
    now++;
    if (!(now % 10000)) _T3Interrupt();
    if (now == next_arrival && incoming_pos < incoming_len) {
      if (!overrun) {
        if (fifo_count == 4) { overrun=true; overflows++; }
        else fifo[(fifo_head+fifo_count++)%4]=incoming[incoming_pos];
      }
      incoming_pos++;
      next_arrival+=87;
    }
  }
}
static void bp_delay_us(unsigned us) { advance(us); }
static void bp_delay_ms(unsigned ms) { advance(ms*1000); }
static bool user_serial_ready_to_read(void) { advance(1); return fifo_count != 0; }
static uint8_t user_serial_read_byte(void) {
  assert(fifo_count);
  uint8_t b=fifo[fifo_head]; fifo_head=(fifo_head+1)%4; fifo_count--; return b;
}
static bool user_serial_check_overflow(void) { advance(1); return overrun; }
static void user_serial_clear_overflow(void) { overrun=false; }
static void user_serial_transmit_character(uint8_t b) { (void)b; }
static void mock_response_append(void) {}

void avrisp_v2_initialise(void) { entry_baud=U1BRG; assert(!INTCON1bits.NSTDIS); }
void avrisp_isp_initialise(void) {}
void avrisp_isp_shutdown(void) {}
void avrisp_xprog_initialise(void) {}
void avrisp_xprog_shutdown(void) {}
void avrisp_xprog_resume_clock(void) {}
void avrisp_v2_process_command(void) {
  assert(avrisp_request_size() == sizeof(expected));
  for (unsigned i=0; i<sizeof(expected); i++) assert(avrisp_read_byte() == expected[i]);
  commands++;
  avrisp_activity_ticks=1;
}
int main(void) {
  expected[0]=0x13; expected[1]=1; expected[2]=0;
  for (unsigned i=3; i<sizeof(expected); i++) expected[i]=i;
  incoming[0]=0x1b; incoming[1]=0x7e; incoming[2]=1; incoming[3]=10; incoming[4]=0x0e;
  memcpy(incoming+5,expected,sizeof(expected));
  incoming_len=5+sizeof(expected);
  uint8_t sum=0;
  for (unsigned i=0; i<incoming_len; i++) sum^=incoming[i];
  incoming[incoming_len++]=sum;
  avrisp_activity_ticks=AVRISP_IDLE_TICKS;
  avrisp_timeout_ticks=AVRISP_TIMEOUT_TICKS;
  avrisp_serial_run();
  assert(commands == 1 && overflows == 0 && incoming_pos == incoming_len);
  U1BRG=68; INTCON1bits.NSTDIS=1;
  avrisp_mkii_enter(AVRISP_TRANSPORT_USB); /* v3 has no USB: immediate cleanup. */
  assert(entry_baud == 34 && U1BRG == 68 && INTCON1bits.NSTDIS == 1);
  puts("AVRISP v3 timed UART: 266-byte payload, no FIFO overrun; baud/nesting restored");
  return 0;
}
