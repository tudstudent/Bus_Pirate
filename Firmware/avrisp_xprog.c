/**
 * @file avrisp_xprog.c
 *
 * @brief AVRISP-MKII personality - XPROG protocol handlers and PDI/TPI
 * physical layer.
 *
 * Port of LUFA's XPROGProtocol.c / XPROGTarget.c (Copyright (C) Dean
 * Camera, 2021; MIT-style licence).  The PIC24 UARTs have no synchronous
 * (USRT) mode, so the 12-bit 8E2 PDI/TPI frames are generated and
 * received by a software engine: the CLK pin is clocked by the firmware
 * and the DATA line (MOSI and MISO joined by two 220 ohm resistors, as in
 * the LUFA design) is driven or read in step.  Reception aligns on the
 * start bit, mirroring the AVR USART receiver LUFA relies on.
 */

#include <stdbool.h>

#include "base.h"
#include "avrisp_mkii.h"
#include "avrisp_v2.h"
#include "avrisp_xprog.h"

#ifdef BP_ENABLE_AVRISP_MKII_SUPPORT

/** Half of one PDI/TPI bit period, in microseconds (~125 kHz clock). */
#define XPROG_BIT_HALF_US 4

/* XPROG parameters reported and set by the host. */
uint32_t avrisp_xprog_nvm_base = 0x010001C0;
uint16_t avrisp_xprog_eeprom_page_size = 32;
uint8_t avrisp_xprog_nvm_cmd_reg = 0x33;
uint8_t avrisp_xprog_nvm_csr_reg = 0x32;
uint8_t avrisp_xprog_selected_protocol = XPROG_PROTOCOL_PDI;

/** True while the programmer drives the DATA line. */
static bool avrisp_xprog_sending;

/* -------------------------------------------------------------------------
 * Physical layer (software synchronous USRT).
 * ------------------------------------------------------------------------- */

/** Returns the even parity bit for the given value. */
static bool avrisp_xprog_parity(uint8_t value) {
  value ^= value >> 4;
  value ^= value >> 2;
  value ^= value >> 1;
  return value & 1;
}

/**
 * Runs one PDI/TPI bit period: the clock falls, the data bit is set up,
 * the clock rises and (optionally) the DATA line is sampled.
 */
static bool avrisp_xprog_bit_period(const bool drive, const bool bit,
                                    const bool sample) {
  bool sampled_level = true;

  BP_CLK = LOW;

  if (drive) {
    BP_MOSI = bit ? HIGH : LOW;
  }

  bp_delay_us(XPROG_BIT_HALF_US);

  BP_CLK = HIGH;
  bp_delay_us(XPROG_BIT_HALF_US);

  if (sample) {
    sampled_level = (BP_MISO == HIGH);
  }

  return sampled_level;
}

static void avrisp_xprog_set_transmit_mode(void) {
  if (!avrisp_xprog_sending) {
    BP_MOSI_DIR = OUTPUT;
    BP_MOSI = HIGH;

    /* Wait for a full clock cycle before driving the line (LUFA parity). */
    bp_delay_us(2 * XPROG_BIT_HALF_US);

    avrisp_xprog_sending = true;
  }
}

static void avrisp_xprog_set_receive_mode(void) {
  if (avrisp_xprog_sending) {
    /* Let the last stop bit period complete, then release the line. */
    bp_delay_us(2 * XPROG_BIT_HALF_US);

    BP_MOSI = LOW;
    BP_MOSI_DIR = INPUT;

    avrisp_xprog_sending = false;
  }
}

void avrisp_xprog_send_byte(const uint8_t byte) {
  avrisp_xprog_set_transmit_mode();

  /* Start bit, 8 data bits (LSB first), even parity, two stop bits. */
  (void)avrisp_xprog_bit_period(true, false, false);

  for (uint8_t bit = 0; bit < 8; bit++) {
    (void)avrisp_xprog_bit_period(true, (byte >> bit) & 1, false);
  }

  (void)avrisp_xprog_bit_period(true, avrisp_xprog_parity(byte), false);
  (void)avrisp_xprog_bit_period(true, true, false);
  (void)avrisp_xprog_bit_period(true, true, false);
}

uint8_t avrisp_xprog_receive_byte(void) {
  avrisp_xprog_set_receive_mode();

  /* Clock the line until the target's start bit is sampled low. */
  for (;;) {
    if (!avrisp_timeout_ticks) {
      return 0xFF;
    }

    if (!avrisp_xprog_bit_period(false, false, true)) {
      break;
    }
  }

  uint8_t value = 0;

  for (uint8_t bit = 0; bit < 8; bit++) {
    if (avrisp_xprog_bit_period(false, false, true)) {
      value |= (1 << bit);
    }
  }

  (void)avrisp_xprog_bit_period(false, false, true); /* parity */
  (void)avrisp_xprog_bit_period(false, false, true); /* stop 1 */
  (void)avrisp_xprog_bit_period(false, false, true); /* stop 2 */

  return value;
}

void avrisp_xprog_send_idle(void) {
  /* One IDLE character: 12 bit periods with the line held high. */
  avrisp_xprog_set_transmit_mode();

  for (uint8_t bit = 0; bit < 12; bit++) {
    (void)avrisp_xprog_bit_period(true, true, false);
  }
}

/* -------------------------------------------------------------------------
 * Target interface management.
 * ------------------------------------------------------------------------- */

void avrisp_xprog_initialise(void) {
  avrisp_xprog_nvm_base = 0x010001C0;
  avrisp_xprog_eeprom_page_size = 32;
  avrisp_xprog_nvm_cmd_reg = 0x33;
  avrisp_xprog_nvm_csr_reg = 0x32;
  avrisp_xprog_selected_protocol = XPROG_PROTOCOL_PDI;
}

void avrisp_xprog_shutdown(void) {
  avrisp_xprog_sending = false;

  BP_CLK_RPOUT = 0;
  BP_MOSI_RPOUT = 0;

  BP_CLK = LOW;
  BP_CLK_DIR = INPUT;
  BP_MOSI = LOW;
  BP_MOSI_DIR = INPUT;
  BP_MISO_DIR = INPUT;

  BP_AUX0 = LOW;
  BP_AUX0_DIR = INPUT;
}

void avrisp_xprog_enable_target_pdi(void) {
  avrisp_xprog_sending = false;

  /* Clock and data become plain outputs (PPS detached). */
  BP_CLK_RPOUT = 0;
  BP_MOSI_RPOUT = 0;
  BP_CLK_DIR = OUTPUT;
  BP_CLK = HIGH;
  BP_MISO_DIR = INPUT;

  /* DATA low for at least 90 ns disables the reset function. */
  BP_MOSI_DIR = OUTPUT;
  BP_MOSI = LOW;
  bp_delay_us(100);

  /* DATA high enables the PDI interface. */
  BP_MOSI = HIGH;
  bp_delay_us(20);

  /* Two IDLEs (24 PDI_CLK cycles) enable the interface. */
  avrisp_xprog_send_idle();
  avrisp_xprog_send_idle();
}

void avrisp_xprog_enable_target_tpi(void) {
  avrisp_xprog_sending = false;

  /* /RESET low for at least 400 ns enables TPI functionality. */
  BP_AUX0_DIR = OUTPUT;
  BP_AUX0 = LOW;
  bp_delay_us(100);

  BP_CLK_RPOUT = 0;
  BP_MOSI_RPOUT = 0;
  BP_CLK_DIR = OUTPUT;
  BP_CLK = HIGH;
  BP_MOSI_DIR = OUTPUT;
  BP_MOSI = HIGH;
  BP_MISO_DIR = INPUT;

  avrisp_xprog_send_idle();
  avrisp_xprog_send_idle();
}

void avrisp_xprog_disable_target_pdi(void) {
  avrisp_xprog_set_receive_mode();

  BP_CLK = LOW;
  BP_CLK_DIR = INPUT;
  BP_MOSI = LOW;
  BP_MOSI_DIR = INPUT;
  BP_MISO_DIR = INPUT;
}

void avrisp_xprog_disable_target_tpi(void) {
  avrisp_xprog_disable_target_pdi();

  BP_AUX0 = LOW;
  BP_AUX0_DIR = INPUT;
}

/* -------------------------------------------------------------------------
 * XPROG protocol handlers.
 * ------------------------------------------------------------------------- */

void avrisp_xprog_set_mode(void) {
  uint8_t protocol = avrisp_read_byte();

  avrisp_response_begin();

  avrisp_xprog_selected_protocol = protocol;

  avrisp_write_byte(CMD_XPROG_SETMODE);
  avrisp_write_byte((protocol != XPROG_PROTOCOL_JTAG) ? STATUS_CMD_OK
                                                      : STATUS_CMD_FAILED);
  avrisp_response_end();
}

static void avrisp_xprog_enter_mode(void) {
  avrisp_response_begin();

  bool enabled = false;

  if (avrisp_xprog_selected_protocol == XPROG_PROTOCOL_PDI) {
    enabled = avrisp_xmega_enable_pdi();
  } else if (avrisp_xprog_selected_protocol == XPROG_PROTOCOL_TPI) {
    enabled = avrisp_tiny_enable_tpi();
  }

  avrisp_write_byte(CMD_XPROG);
  avrisp_write_byte(XPROG_CMD_ENTER_PROGMODE);
  avrisp_write_byte(enabled ? XPROG_ERR_OK : XPROG_ERR_FAILED);
  avrisp_response_end();
}

static void avrisp_xprog_leave_mode(void) {
  avrisp_response_begin();

  if (avrisp_xprog_selected_protocol == XPROG_PROTOCOL_PDI) {
    avrisp_xmega_disable_pdi();
  } else {
    avrisp_tiny_disable_tpi();
  }

  avrisp_write_byte(CMD_XPROG);
  avrisp_write_byte(XPROG_CMD_LEAVE_PROGMODE);
  avrisp_write_byte(XPROG_ERR_OK);
  avrisp_response_end();
}

static void avrisp_xprog_erase(void) {
  uint8_t memory_type = avrisp_read_byte();
  uint32_t address = 0;

  for (uint8_t index = 0; index < sizeof(address); index++) {
    address = (address << 8) | avrisp_read_byte();
  }

  avrisp_response_begin();

  uint8_t status = XPROG_ERR_OK;

  if (avrisp_xprog_selected_protocol == XPROG_PROTOCOL_PDI) {
    uint8_t erase_command;

    switch (memory_type) {
    case XPROG_ERASE_CHIP:
      erase_command = XMEGA_NVM_CMD_CHIPERASE;
      break;
    case XPROG_ERASE_APP:
      erase_command = XMEGA_NVM_CMD_ERASEAPPSEC;
      break;
    case XPROG_ERASE_BOOT:
      erase_command = XMEGA_NVM_CMD_ERASEBOOTSEC;
      break;
    case XPROG_ERASE_EEPROM:
      erase_command = XMEGA_NVM_CMD_ERASEEEPROM;
      break;
    case XPROG_ERASE_APP_PAGE:
      erase_command = XMEGA_NVM_CMD_ERASEAPPSECPAGE;
      break;
    case XPROG_ERASE_BOOT_PAGE:
      erase_command = XMEGA_NVM_CMD_ERASEBOOTSECPAGE;
      break;
    case XPROG_ERASE_EEPROM_PAGE:
      erase_command = XMEGA_NVM_CMD_ERASEEEPROMPAGE;
      break;
    case XPROG_ERASE_USERSIG:
      erase_command = XMEGA_NVM_CMD_ERASEUSERSIG;
      break;
    default:
      erase_command = XMEGA_NVM_CMD_NOOP;
      break;
    }

    if (!avrisp_xmega_erase_memory(erase_command, address)) {
      status = XPROG_ERR_TIMEOUT;
    }
  } else {
    uint8_t erase_command = (memory_type == XPROG_ERASE_CHIP)
                                ? TINY_NVM_CMD_CHIPERASE
                                : TINY_NVM_CMD_SECTIONERASE;

    if (!avrisp_tiny_erase_memory(erase_command, address)) {
      status = XPROG_ERR_TIMEOUT;
    }
  }

  avrisp_write_byte(CMD_XPROG);
  avrisp_write_byte(XPROG_CMD_ERASE);
  avrisp_write_byte(status);
  avrisp_response_end();
}

static void avrisp_xprog_write_memory(void) {
  uint8_t memory_type = avrisp_read_byte();
  uint8_t page_mode = avrisp_read_byte();
  uint32_t address = 0;
  uint8_t length_high;
  uint8_t length_low;
  uint16_t length;

  for (uint8_t index = 0; index < sizeof(address); index++) {
    address = (address << 8) | avrisp_read_byte();
  }

  length_high = avrisp_read_byte();
  length_low = avrisp_read_byte();
  length = ((uint16_t)length_high << 8) | length_low;

  if (length >= 256) {
    /* The request cannot be buffered; hosts stay well below. */
    avrisp_discard_incoming();

    avrisp_response_begin();
    avrisp_write_byte(CMD_XPROG);
    avrisp_write_byte(XPROG_CMD_WRITE_MEM);
    avrisp_write_byte(XPROG_ERR_FAILED);
    avrisp_response_end();
    return;
  }

  for (uint16_t index = 0; index < length; index++) {
    avrisp_command_buffer[index] = avrisp_read_byte();
  }

  avrisp_response_begin();

  uint8_t status = XPROG_ERR_OK;

  if (avrisp_xprog_selected_protocol == XPROG_PROTOCOL_PDI) {
    uint8_t write_command = XMEGA_NVM_CMD_WRITEFLASHPAGE;
    uint8_t write_buffer_command = XMEGA_NVM_CMD_LOADFLASHPAGEBUFF;
    uint8_t erase_buffer_command = XMEGA_NVM_CMD_ERASEFLASHPAGEBUFF;
    bool paged_memory = true;

    switch (memory_type) {
    case XPROG_MEM_TYPE_APPL:
      write_command = XMEGA_NVM_CMD_WRITEAPPSECPAGE;
      break;
    case XPROG_MEM_TYPE_BOOT:
      write_command = XMEGA_NVM_CMD_WRITEBOOTSECPAGE;
      break;
    case XPROG_MEM_TYPE_EEPROM:
      write_command = XMEGA_NVM_CMD_ERASEWRITEEEPROMPAGE;
      write_buffer_command = XMEGA_NVM_CMD_LOADEEPROMPAGEBUFF;
      erase_buffer_command = XMEGA_NVM_CMD_ERASEEEPROMPAGEBUFF;
      break;
    case XPROG_MEM_TYPE_USERSIG:
      write_command = XMEGA_NVM_CMD_WRITEUSERSIG;
      break;
    case XPROG_MEM_TYPE_FUSE:
      write_command = XMEGA_NVM_CMD_WRITEFUSE;
      paged_memory = false;
      break;
    case XPROG_MEM_TYPE_LOCKBITS:
      write_command = XMEGA_NVM_CMD_WRITELOCK;
      paged_memory = false;
      break;
    }

    if ((paged_memory &&
         !avrisp_xmega_write_page(write_buffer_command, erase_buffer_command,
                                  write_command, page_mode, address,
                                  avrisp_command_buffer, length)) ||
        (!paged_memory &&
         !avrisp_xmega_write_byte(write_command, address,
                                  avrisp_command_buffer[0]))) {
      status = XPROG_ERR_TIMEOUT;
    }
  } else {
    if (!avrisp_tiny_write_memory(address, avrisp_command_buffer, length)) {
      status = XPROG_ERR_TIMEOUT;
    }
  }

  avrisp_write_byte(CMD_XPROG);
  avrisp_write_byte(XPROG_CMD_WRITE_MEM);
  avrisp_write_byte(status);
  avrisp_response_end();
}

static void avrisp_xprog_read_memory(void) {
  uint8_t memory_type = avrisp_read_byte();
  uint32_t address = 0;
  uint8_t length_high;
  uint8_t length_low;
  uint16_t length;

  for (uint8_t index = 0; index < sizeof(address); index++) {
    address = (address << 8) | avrisp_read_byte();
  }

  (void)memory_type;

  length_high = avrisp_read_byte();
  length_low = avrisp_read_byte();
  length = ((uint16_t)length_high << 8) | length_low;

  if (length > 256) {
    /* The response cannot buffer this; hosts stay at or below 256. */
    avrisp_discard_incoming();

    avrisp_response_begin();
    avrisp_write_byte(CMD_XPROG);
    avrisp_write_byte(XPROG_CMD_READ_MEM);
    avrisp_write_byte(XPROG_ERR_FAILED);
    avrisp_response_end();
    return;
  }

  avrisp_response_begin();

  uint8_t status = XPROG_ERR_OK;

  if (avrisp_xprog_selected_protocol == XPROG_PROTOCOL_PDI) {
    if (!avrisp_xmega_read_memory(address, avrisp_command_buffer, length)) {
      status = XPROG_ERR_TIMEOUT;
    }
  } else {
    if (!avrisp_tiny_read_memory(address, avrisp_command_buffer, length)) {
      status = XPROG_ERR_TIMEOUT;
    }
  }

  avrisp_write_byte(CMD_XPROG);
  avrisp_write_byte(XPROG_CMD_READ_MEM);
  avrisp_write_byte(status);

  if (status == XPROG_ERR_OK) {
    for (uint16_t index = 0; index < length; index++) {
      avrisp_write_byte(avrisp_command_buffer[index]);
    }
  }

  avrisp_response_end();
}

static void avrisp_xprog_read_crc(void) {
  uint8_t crc_type = avrisp_read_byte();

  avrisp_response_begin();

  uint32_t memory_crc = 0;
  uint8_t status = XPROG_ERR_OK;

  if (avrisp_xprog_selected_protocol == XPROG_PROTOCOL_PDI) {
    uint8_t crc_command;

    switch (crc_type) {
    case XPROG_CRC_APP:
      crc_command = XMEGA_NVM_CMD_APPCRC;
      break;
    case XPROG_CRC_BOOT:
      crc_command = XMEGA_NVM_CMD_BOOTCRC;
      break;
    default:
      crc_command = XMEGA_NVM_CMD_FLASHCRC;
      break;
    }

    if (!avrisp_xmega_get_crc(crc_command, &memory_crc)) {
      status = XPROG_ERR_TIMEOUT;
    }
  } else {
    /* TPI does not support memory CRCs. */
    status = XPROG_ERR_FAILED;
  }

  avrisp_write_byte(CMD_XPROG);
  avrisp_write_byte(XPROG_CMD_CRC);
  avrisp_write_byte(status);

  if (status == XPROG_ERR_OK) {
    avrisp_write_byte(memory_crc >> 16);
    avrisp_write_byte(memory_crc & 0xFF);
    avrisp_write_byte((memory_crc >> 8) & 0xFF);
  }

  avrisp_response_end();
}

static void avrisp_xprog_set_param(void) {
  uint8_t param = avrisp_read_byte();
  uint8_t status = XPROG_ERR_OK;

  switch (param) {
  case XPROG_PARAM_NVMBASE: {
    uint32_t value = 0;

    for (uint8_t index = 0; index < sizeof(value); index++) {
      value = (value << 8) | avrisp_read_byte();
    }

    avrisp_xprog_nvm_base = value;
    break;
  }

  case XPROG_PARAM_EEPPAGESIZE: {
    uint8_t high = avrisp_read_byte();
    uint8_t low = avrisp_read_byte();

    avrisp_xprog_eeprom_page_size = ((uint16_t)high << 8) | low;
    break;
  }

  case XPROG_PARAM_NVMCMD_REG:
    avrisp_xprog_nvm_cmd_reg = avrisp_read_byte();
    break;

  case XPROG_PARAM_NVMCSR_REG:
    avrisp_xprog_nvm_csr_reg = avrisp_read_byte();
    break;

  case XPROG_PARAM_UNKNOWN_1:
    /* Undocumented parameter added in AVRStudio 5.1; acknowledge and
       discard or communication with AVRStudio 5.1 fails (LUFA parity). */
    (void)avrisp_read_byte();
    (void)avrisp_read_byte();
    break;

  default:
    status = XPROG_ERR_FAILED;
    break;
  }

  avrisp_response_begin();
  avrisp_write_byte(CMD_XPROG);
  avrisp_write_byte(XPROG_CMD_SET_PARAM);
  avrisp_write_byte(status);
  avrisp_response_end();
}

void avrisp_xprog_command(void) {
  uint8_t command = avrisp_read_byte();

  switch (command) {
  case XPROG_CMD_ENTER_PROGMODE:
    avrisp_xprog_enter_mode();
    break;

  case XPROG_CMD_LEAVE_PROGMODE:
    avrisp_xprog_leave_mode();
    break;

  case XPROG_CMD_ERASE:
    avrisp_xprog_erase();
    break;

  case XPROG_CMD_WRITE_MEM:
    avrisp_xprog_write_memory();
    break;

  case XPROG_CMD_READ_MEM:
    avrisp_xprog_read_memory();
    break;

  case XPROG_CMD_CRC:
    avrisp_xprog_read_crc();
    break;

  case XPROG_CMD_SET_PARAM:
    avrisp_xprog_set_param();
    break;

  default:
    /* LUFA ignores unknown XPROG subcommands without a reply; hosts
       only send the commands above. */
    break;
  }
}

#endif /* BP_ENABLE_AVRISP_MKII_SUPPORT */