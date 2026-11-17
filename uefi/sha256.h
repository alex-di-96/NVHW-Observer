/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef NVHW_SHA256_H
#define NVHW_SHA256_H
#include <stddef.h>
#include <stdint.h>
typedef struct { uint32_t h[8]; uint64_t bytes; size_t used; uint8_t block[64]; } nvhw_sha256;
void nvhw_sha256_init(nvhw_sha256 *s);
void nvhw_sha256_update(nvhw_sha256 *s, const void *data, size_t length);
void nvhw_sha256_final(nvhw_sha256 *s, uint8_t digest[32]);
void nvhw_sha256_hex(const uint8_t digest[32], char hex[65]);
#endif
