#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

using gpio_num_t = int;

#if !defined(__APPLE__) && !defined(__FreeBSD__)
static inline size_t strlcpy(char *destination, const char *source, size_t size) {
  const size_t source_length = strlen(source);
  if (size > 0U) {
    const size_t copied = source_length >= size ? size - 1U : source_length;
    memcpy(destination, source, copied);
    destination[copied] = '\0';
  }
  return source_length;
}
#endif
