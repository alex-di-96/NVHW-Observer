/* SPDX-License-Identifier: GPL-2.0-only
 * NVHW-observer M1/M2. Passive GPU observations; no GPU write/reset interface.
 * The only PCI write is scoped COMMAND.MEMORY with verified restoration.
 * Log transport adapted from HW_Tune diagnostic/diag.c (MIT).
 */
#include <efi.h>
#include <efilib.h>
#include <efipciio.h>
#include <stdarg.h>
#include "sha256.h"
#include "build_identity.h"

static EFI_FILE_HANDLE root;
static EFI_HANDLE image;
#if !NVHW_TEST
static EFI_PCI_IO_PROTOCOL *gpu;
#endif
static CHAR16 log_path[96];
static UINT64 run_id;
static UINTN file_seq,seg,bus,dev,fun,command_writes;
static BOOLEAN log_ok=TRUE,saved=FALSE,changed=FALSE;
static UINT16 original_command;
static UINT64 bar_base,bar_size;
static UINT32 pmcsr;

static UINT64 ticks(void) { UINT32 lo,hi; __asm__ volatile("rdtsc":"=a"(lo),"=d"(hi));return ((UINT64)hi<<32)|lo; }
static BOOLEAN line(const CHAR16 *fmt,...) {
    CHAR16 payload[800],wide[900];char ascii[900];va_list ap;
    EFI_FILE_HANDLE file=NULL;EFI_STATUS st,closed;UINTN n=0,written;
    if(!log_ok || !root){log_ok=FALSE;return FALSE;}
    va_start(ap,fmt);VSPrint(payload,sizeof(payload),(CHAR16 *)fmt,ap);va_end(ap);
    SPrint(wide,sizeof(wide),L"NVHW1 run=%016lx %s",run_id,payload);
    while(wide[n] && n<sizeof(ascii)-3){ascii[n]=(char)wide[n];n++;}
    if(wide[n]){log_ok=FALSE;return FALSE;}
    ascii[n++]='\r';ascii[n++]='\n';written=n;Print(L"%s\r\n",wide);
    st=uefi_call_wrapper(root->Open,5,root,&file,log_path,EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE,0);
    if(st==EFI_SUCCESS)st=uefi_call_wrapper(file->SetPosition,2,file,~(UINT64)0);
    if(st==EFI_SUCCESS)st=uefi_call_wrapper(file->Write,3,file,&written,ascii);
    if(st==EFI_SUCCESS && written!=n)st=EFI_DEVICE_ERROR;
    if(st==EFI_SUCCESS)st=uefi_call_wrapper(file->Flush,1,file);
    if(file){closed=uefi_call_wrapper(file->Close,1,file);if(st==EFI_SUCCESS)st=closed;}
    if(st!=EFI_SUCCESS)log_ok=FALSE;
    return log_ok;
}
static EFI_STATUS new_log(void) {
    for(file_seq=1;file_seq<=9999;file_seq++){
        EFI_FILE_HANDLE file=NULL;
        SPrint(log_path,sizeof(log_path),L"\\HWT\\%s-%04d.log",NVHW_LOG_STEM,file_seq);
        EFI_STATUS st=uefi_call_wrapper(root->Open,5,root,&file,log_path,EFI_FILE_MODE_READ,0);
        if(st==EFI_SUCCESS){st=uefi_call_wrapper(file->Close,1,file);if(st!=EFI_SUCCESS)return st;continue;}
        if(st!=EFI_NOT_FOUND)return st;
        st=uefi_call_wrapper(root->Open,5,root,&file,log_path,EFI_FILE_MODE_CREATE|EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE,0);
        if(st!=EFI_SUCCESS)return st;
        return uefi_call_wrapper(file->Close,1,file);
    }
    return EFI_VOLUME_FULL;
}
static EFI_STATUS file_hash(CHAR16 *path,char hex[65]) {
    EFI_FILE_HANDLE file=NULL;UINT8 buffer[4096],digest[32];UINTN total=0,n;
    nvhw_sha256 state;nvhw_sha256_init(&state);
    EFI_STATUS st=uefi_call_wrapper(root->Open,5,root,&file,path,EFI_FILE_MODE_READ,0);
    if(st!=EFI_SUCCESS)return st;
    do{
        n=sizeof(buffer);st=uefi_call_wrapper(file->Read,3,file,&n,buffer);
        if(st!=EFI_SUCCESS)break;
        total+=n;if(total>16*1024*1024){st=EFI_BAD_BUFFER_SIZE;break;}
        nvhw_sha256_update(&state,buffer,n);
    }while(n);
    EFI_STATUS closed=uefi_call_wrapper(file->Close,1,file);
    if(st==EFI_SUCCESS)st=closed;
    if(st==EFI_SUCCESS){nvhw_sha256_final(&state,digest);nvhw_sha256_hex(digest,hex);}
    return st;
}

#if NVHW_TEST
static UINT16 mock_command=NVHW_TEST==9?0x107:0x100;
static EFI_STATUS select_gpu(void){seg=0;bus=3;dev=0;fun=0;return NVHW_TEST==7?EFI_UNSUPPORTED:EFI_SUCCESS;}
static EFI_STATUS cfg32(UINT32 off,UINT32 *v){
    *v=off==4?0x00100000U|mock_command:off==0x10?0xde000000:off==0x34?0x40:off==0x40?1:0;
    if(off==0x44 && NVHW_TEST==6)*v=3;
    return EFI_SUCCESS;
}
static EFI_STATUS command_read(UINT16 *v){*v=mock_command;return EFI_SUCCESS;}
static EFI_STATUS command_write(UINT16 v){
    command_writes++;
    if(NVHW_TEST==5 && v==0x100)return EFI_DEVICE_ERROR;
    mock_command=v; /* mode8: failed enable may still have taken effect */
    return NVHW_TEST==8 && v!=0x100?EFI_DEVICE_ERROR:EFI_SUCCESS;
}
static EFI_STATUS read_words(UINT32 off,UINTN count,UINT32 *values){
    if(NVHW_TEST==4 && off==0x21378)return EFI_DEVICE_ERROR;
    for(UINTN i=0;i<count;i++){
        UINT32 a=off+4*i;
        values[i]=a==0?(NVHW_TEST==2?0xdeadbeef:PROFILE_BOOT0):a==0x21378?7:a==0x409650?0xffffff8f:0;
        if(NVHW_TEST==3 && a==0x300000)values[i]=1;
    }
    return EFI_SUCCESS;
}
static EFI_STATUS get_bar_size(void){bar_size=0x1000000;return EFI_SUCCESS;}
#else
static EFI_STATUS select_gpu(void){
    EFI_GUID guid=EFI_PCI_IO_PROTOCOL_GUID;EFI_HANDLE *handles=NULL;UINTN count=0,matches=0;
    EFI_STATUS st=uefi_call_wrapper(BS->LocateHandleBuffer,5,ByProtocol,&guid,NULL,&count,&handles);
    if(st!=EFI_SUCCESS)return st;
    for(UINTN i=0;i<count;i++){
        EFI_PCI_IO_PROTOCOL *p=NULL;UINT32 id=0,sub=0;UINTN s,b,d,f;
        if(uefi_call_wrapper(BS->HandleProtocol,3,handles[i],&guid,(void **)&p)!=EFI_SUCCESS)continue;
        st=uefi_call_wrapper(p->Pci.Read,5,p,EfiPciIoWidthUint32,0,1,&id);
        if(st!=EFI_SUCCESS){FreePool(handles);return st;}
        if(id!=PROFILE_PCI)continue;
        st=uefi_call_wrapper(p->Pci.Read,5,p,EfiPciIoWidthUint32,0x2c,1,&sub);
        if(st!=EFI_SUCCESS){FreePool(handles);return st;}
        if(sub!=PROFILE_SUB)continue;
        st=uefi_call_wrapper(p->GetLocation,5,p,&s,&b,&d,&f);
        if(st!=EFI_SUCCESS){FreePool(handles);return st;}
        matches++;gpu=p;seg=s;bus=b;dev=d;fun=f;
    }
    FreePool(handles);return matches==1?EFI_SUCCESS:matches?EFI_UNSUPPORTED:EFI_NOT_FOUND;
}
static EFI_STATUS cfg32(UINT32 off,UINT32 *v){return uefi_call_wrapper(gpu->Pci.Read,5,gpu,EfiPciIoWidthUint32,off,1,v);}
static EFI_STATUS command_read(UINT16 *v){return uefi_call_wrapper(gpu->Pci.Read,5,gpu,EfiPciIoWidthUint16,4,1,v);}
static EFI_STATUS command_write(UINT16 v){command_writes++;return uefi_call_wrapper(gpu->Pci.Write,5,gpu,EfiPciIoWidthUint16,4,1,&v);}
static EFI_STATUS read_words(UINT32 off,UINTN count,UINT32 *values){return uefi_call_wrapper(gpu->Mem.Read,6,gpu,EfiPciIoWidthUint32,0,off,count,values);}
static UINT64 le64(const UINT8 *p){UINT64 v=0;for(UINTN i=0;i<8;i++)v|=(UINT64)p[i]<<(8*i);return v;}
static EFI_STATUS get_bar_size(void){
    void *resource=NULL;EFI_STATUS st=uefi_call_wrapper(gpu->GetBarAttributes,4,gpu,0,NULL,&resource);
    if(st!=EFI_SUCCESS)return st;
    if(!resource)return EFI_DEVICE_ERROR;
    UINT8 *p=resource;
    /* ACPI QWord Address Space descriptor, memory resource, 43-byte payload. */
    if(p[0]!=0x8a || p[1]!=43 || p[2]!=0 || p[3]!=0)st=EFI_UNSUPPORTED;
    else bar_size=le64(p+38);
    FreePool(resource);return st;
}
#endif

static EFI_STATUS access_guards(void){
    UINT32 value=0,lo=0,hi=0;UINT8 seen[256]={0};BOOLEAN found=FALSE;
    EFI_STATUS st=cfg32(4,&value);if(st!=EFI_SUCCESS)return st;
    if(!(value&(1U<<20)))return EFI_UNSUPPORTED;
    st=cfg32(0x34,&value);if(st!=EFI_SUCCESS)return st;
    UINT32 cap=value&255;
    for(UINTN i=0;cap && i<48;i++){
        if(cap<0x40 || cap>0xfc || (cap&3) || seen[cap])return EFI_UNSUPPORTED;
        seen[cap]=1;st=cfg32(cap,&value);if(st!=EFI_SUCCESS)return st;
        if((value&255)==1){
            if(cap>0xf8)return EFI_UNSUPPORTED;
            st=cfg32(cap+4,&pmcsr);if(st!=EFI_SUCCESS)return st;
            if(pmcsr&3)return EFI_NOT_READY;
            found=TRUE;break;
        }
        cap=(value>>8)&255;
    }
    if(!found)return EFI_UNSUPPORTED;
    st=cfg32(0x10,&lo);if(st!=EFI_SUCCESS)return st;
    if((lo&1) || lo==0xffffffffU || ((lo>>1)&3)==1 || ((lo>>1)&3)==3)return EFI_UNSUPPORTED;
    if(((lo>>1)&3)==2){st=cfg32(0x14,&hi);if(st!=EFI_SUCCESS)return st;}
    bar_base=((UINT64)hi<<32)|(lo&~15U);if(!bar_base)return EFI_UNSUPPORTED;
    st=get_bar_size();if(st!=EFI_SUCCESS)return st;
    if(bar_size<0x310000)return EFI_BAD_BUFFER_SIZE;
    return EFI_SUCCESS;
}
static EFI_STATUS restore(void){
    UINT16 current=0;EFI_STATUS write_st=EFI_SUCCESS,read_st=EFI_SUCCESS;
    if(!saved)return EFI_SUCCESS;
    if(changed)write_st=command_write(original_command);
    read_st=command_read(&current);saved=FALSE; /* never retry a failed restore */
    line(L"RESTORE original=%04x final=%04x write_status=%016lx read_status=%016lx writes=%d",
         original_command,current,(UINT64)write_st,(UINT64)read_st,command_writes);
    return write_st==EFI_SUCCESS && read_st==EFI_SUCCESS && current==original_command?EFI_SUCCESS:EFI_DEVICE_ERROR;
}
static BOOLEAN valid(UINT32 address,UINT32 value,EFI_STATUS st){
    return st==EFI_SUCCESS && (value&0xffff0000U)!=0xbadf0000U && value!=0xdec0ffeeU && value!=0xdece30fbU && (value!=0xffffffffU || address==0x409650);
}
static EFI_STATUS rom_hash(char hex[65]){
    UINT32 words[256];UINT8 digest[32];nvhw_sha256 state;nvhw_sha256_init(&state);
    for(UINT32 off=0;off<65536;off+=sizeof(words)){
        EFI_STATUS st=read_words(0x300000+off,256,words);if(st!=EFI_SUCCESS)return st;
        nvhw_sha256_update(&state,words,sizeof(words));
    }
    nvhw_sha256_final(&state,digest);nvhw_sha256_hex(digest,hex);return EFI_SUCCESS;
}
static void stop(EFI_STATUS st,CHAR16 *reason){
    line(L"RESULT outcome=stopped reason=%s status=%016lx",reason,(UINT64)st);
    if(root){uefi_call_wrapper(root->Close,1,root);root=NULL;}
    Print(L"NVHW STOP: %s (%r). Power off, remove AC for 60 seconds. Do not Reset.\r\n",reason,st);
    for(;;)uefi_call_wrapper(BS->Stall,1,250000);
}

EFI_STATUS efi_main(EFI_HANDLE handle,EFI_SYSTEM_TABLE *table){
    EFI_LOADED_IMAGE *li=NULL;EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *fs=NULL;EFI_HANDLE next=NULL;
    EFI_STATUS st;UINT16 active=0;UINT32 boot0=0;UINTN usable=0,transport_errors=0;
    CHAR16 *reason=L"setup";char hex[65];EFI_TIME time;
    InitializeLib(handle,table);image=handle;run_id=ticks();
    st=uefi_call_wrapper(BS->SetWatchdogTimer,4,0,0,0,NULL);if(st!=EFI_SUCCESS)stop(st,reason);
    st=uefi_call_wrapper(BS->HandleProtocol,3,image,&LoadedImageProtocol,(void **)&li);if(st!=EFI_SUCCESS)stop(st,reason);
    st=uefi_call_wrapper(BS->HandleProtocol,3,li->DeviceHandle,&FileSystemProtocol,(void **)&fs);if(st!=EFI_SUCCESS)stop(st,reason);
    st=uefi_call_wrapper(fs->OpenVolume,2,fs,&root);if(st!=EFI_SUCCESS)stop(st,reason);
    st=new_log();if(st!=EFI_SUCCESS){log_ok=FALSE;stop(st,L"log_create");}
    line(L"RUN schema=1 test=%d source=%a profile=%a words=%d seq=%d",NVHW_TEST,NVHW_SOURCE_SHA,PROFILE_SHA,PROFILE_WORDS,file_seq);
#if NVHW_TEST
    Print(L"NVHW_TEST_ONLY: synthetic GPU; never deploy.\r\n");
#endif
    if(uefi_call_wrapper(RT->GetTime,2,&time,NULL)==EFI_SUCCESS)
        line(L"RTC date=%04d-%02d-%02dT%02d:%02d:%02d timezone=%d",time.Year,time.Month,time.Day,time.Hour,time.Minute,time.Second,time.TimeZone);
    reason=L"self_identity";
    if(!li->FilePath || DevicePathType(li->FilePath)!=MEDIA_DEVICE_PATH || DevicePathSubType(li->FilePath)!=MEDIA_FILEPATH_DP || DevicePathNodeLength(li->FilePath)<6 || !IsDevicePathEnd(NextDevicePathNode(li->FilePath)))stop(EFI_UNSUPPORTED,reason);
    st=file_hash(((FILEPATH_DEVICE_PATH *)li->FilePath)->PathName,hex);if(st!=EFI_SUCCESS)stop(st,reason);
    line(L"SELF sha256=%a",hex);
    reason=L"successor_identity";st=file_hash(L"\\EFI\\HWT\\UNLOCK.EFI",hex);
    if(st!=EFI_SUCCESS || CompareMem(hex,NVHW_SUCCESSOR_SHA,65))stop(EFI_ACCESS_DENIED,reason);
    line(L"NEXT sha256=%a",hex);
    if(!log_ok)stop(EFI_DEVICE_ERROR,L"log_write");
    reason=L"target_selection";st=select_gpu();if(st!=EFI_SUCCESS)stop(st,reason);
    line(L"TARGET bdf=%04x:%02x:%02x.%x pci=%08x subsystem=%08x",seg,bus,dev,fun,PROFILE_PCI,PROFILE_SUB);
    reason=L"access_guards";st=access_guards();if(st!=EFI_SUCCESS)stop(st,reason);
    line(L"GUARDS pmcsr=%08x bar_base=%016lx bar_size=%016lx",pmcsr,bar_base,bar_size);
    st=command_read(&original_command);if(st!=EFI_SUCCESS || original_command==0xffff)stop(EFI_DEVICE_ERROR,L"command_read");
    if(!log_ok)stop(EFI_DEVICE_ERROR,L"log_write");
    saved=TRUE;
    line(L"ACCESS original=%04x expected=%04x",original_command,original_command|2);
    if(!log_ok){st=EFI_DEVICE_ERROR;reason=L"log_write";goto failed;}
    reason=L"command_enable";
    if(!(original_command&2)){changed=TRUE;st=command_write(original_command|2);if(st!=EFI_SUCCESS)goto failed;}
    st=command_read(&active);line(L"ACTIVE value=%04x status=%016lx",active,(UINT64)st);
    if(st!=EFI_SUCCESS || active!=(original_command|2)){st=EFI_DEVICE_ERROR;goto failed;}
    if(!log_ok){st=EFI_DEVICE_ERROR;reason=L"log_write";goto failed;}
    reason=L"boot0";st=read_words(0,1,&boot0);
    line(L"BOOT0 value=%08x status=%016lx",boot0,(UINT64)st);
    if(st!=EFI_SUCCESS || boot0!=PROFILE_BOOT0){st=EFI_UNSUPPORTED;goto failed;}
    reason=L"rom_identity";st=rom_hash(hex);if(st!=EFI_SUCCESS)goto failed;
    line(L"ROM sha256=%a bytes=65536 offset=00300000",hex);
    if(CompareMem(hex,NVHW_ROM_SHA,65)){st=EFI_UNSUPPORTED;goto failed;}
    if(!log_ok){st=EFI_DEVICE_ERROR;reason=L"log_write";goto failed;}
    line(L"BEGIN phase=pre_compute words=%d ticks=%016lx atomic=0 gpu_mmio_writes=0",PROFILE_WORDS,ticks());
    for(UINTN i=0;i<PROFILE_WORDS && log_ok;i++){
        UINT32 value=0;EFI_STATUS rs=read_words(profile_registers[i],1,&value);
        BOOLEAN ok=valid(profile_registers[i],value,rs);usable+=ok;transport_errors+=(rs!=EFI_SUCCESS);
        line(L"WORD index=%d address=%08x value=%08x status=%016lx valid=%d",i,profile_registers[i],value,(UINT64)rs,ok);
    }
    line(L"END words=%d usable=%d transport_errors=%d ticks=%016lx",PROFILE_WORDS,usable,transport_errors,ticks());
    st=restore();if(st!=EFI_SUCCESS)stop(st,L"command_restore");
    if(transport_errors)stop(EFI_DEVICE_ERROR,L"snapshot_transport");
    if(!log_ok)stop(EFI_DEVICE_ERROR,L"log_write");
    EFI_DEVICE_PATH *path=FileDevicePath(li->DeviceHandle,L"\\EFI\\HWT\\UNLOCK.EFI");
    if(!path)stop(EFI_OUT_OF_RESOURCES,L"successor_path");
    st=uefi_call_wrapper(BS->LoadImage,6,FALSE,image,path,NULL,0,&next);FreePool(path);
    if(st!=EFI_SUCCESS)stop(st,L"successor_load");
    line(L"RESULT outcome=complete usable=%d words=%d functional_tests=not_measured",usable,PROFILE_WORDS);
    if(!line(L"HANDOFF sha256=%a confirmation=successor",NVHW_SUCCESSOR_SHA))stop(EFI_DEVICE_ERROR,L"log_write");
    st=uefi_call_wrapper(root->Close,1,root);root=NULL;if(st!=EFI_SUCCESS)stop(st,L"log_close");
    st=uefi_call_wrapper(BS->StartImage,3,next,NULL,NULL);stop(st,L"successor_returned");
    return EFI_ABORTED;
failed:
    if(restore()!=EFI_SUCCESS)stop(EFI_DEVICE_ERROR,L"command_restore");
    stop(st,reason);return EFI_ABORTED;
}
