/* SPDX-License-Identifier: GPL-2.0-only
 * QEMU-only exit marker, no GPU/device passthrough. Never deploy on hardware.
 */
#include <efi.h>
EFI_STATUS efi_main(EFI_HANDLE image,EFI_SYSTEM_TABLE *table){
    (void)image;(void)table;
    const char *s="NVHW_QEMU_SUCCESSOR_EXECUTED\n";
    while(*s){__asm__ volatile("outb %0,%1"::"a"(*s++),"Nd"((UINT16)0x402));}
    __asm__ volatile("outl %0,%1"::"a"((UINT32)0x10),"Nd"((UINT16)0xf4));
    for(;;)__asm__ volatile("hlt");
    return EFI_SUCCESS;
}
