"""Read only installed Mono PE file; no attach, load, invocation, or memory API."""
from pathlib import Path
import hashlib
import json
import struct

HERE=Path(__file__).resolve().parent
DLL=Path('D:/Hearthstone/MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll')
raw=DLL.read_bytes()
digest=hashlib.sha256(raw).hexdigest()
assert digest=='86a5a4de6bcd74a637d63c96d822dc989d4ffaed6ef1c15c0e6e1f528ae6708f'
u16=lambda o:struct.unpack_from('<H',raw,o)[0]
u32=lambda o:struct.unpack_from('<I',raw,o)[0]
assert raw[:2]==b'MZ'
pe=u32(60);assert raw[pe:pe+4]==b'PE\0\0'
opt=pe+24;assert u16(opt)==0x20b
section_table=opt+u16(pe+20)
sections=[struct.unpack_from('<IIII',raw,section_table+i*40+8) for i in range(u16(pe+6))]
def file_offset(rva,size=1):
    for virtual_size,virtual_address,raw_size,pointer in sections:
        delta=rva-virtual_address
        if 0<=delta and delta+size<=raw_size:
            return pointer+delta
    raise ValueError('RVA is not backed by file bytes')
ex=file_offset(u32(opt+112),40)
functions,names,fa,na,oa=struct.unpack_from('<IIIII',raw,ex+20)
assert 0<names<=65536 and 0<functions<=65536
fa=file_offset(fa,functions*4);na=file_offset(na,names*4);oa=file_offset(oa,names*2)
wanted={'mono_class_instance_size','mono_class_get_element_class','mono_array_element_size','mono_class_value_size','mono_get_root_domain'}
exports={}
for i in range(names):
    offset=file_offset(u32(na+i*4));end=raw.index(0,offset,offset+256)
    name=raw[offset:end].decode('ascii')
    if name not in wanted:continue
    ordinal=u16(oa+i*2);assert ordinal<functions
    rva=u32(fa+ordinal*4);offset=file_offset(rva,160)
    data=raw[offset:offset+160]
    exports[name]={'rva':rva,'file_offset':offset,'window_bytes':160,'window_sha256':hashlib.sha256(data).hexdigest(),'hex':data.hex(' ')}
def code(name):return bytes.fromhex(exports[name]['hex'])
assert set(exports)==wanted
assert code('mono_class_get_element_class')[:4]==bytes.fromhex('48 8b 01 c3')
assert code('mono_class_instance_size')[20:23]==bytes.fromhex('8b 43 1c')
assert code('mono_class_instance_size')[29:32]==bytes.fromhex('8b 41 1c')
assert bytes.fromhex('8b 83 90 00 00 00') in code('mono_array_element_size')
assert bytes.fromhex('8b 73 1c') in code('mono_class_value_size')
assert bytes.fromhex('83 ee 10') in code('mono_class_value_size')
assert code('mono_get_root_domain')[:3]==bytes.fromhex('48 8b 05') and code('mono_get_root_domain')[7]==0xc3
report={
 'source':str(DLL),'source_sha256':digest,'source_bytes':len(raw),
 'method':'Read disk PE export/name/ordinal/RVA tables, verify literal x64 machine-code bytes; do not execute any export or access any process.',
 'exports':exports,
 'decoded_proofs':[
  {'function':'mono_class_get_element_class','bytes':'48 8B 01 C3','meaning':'MOV RAX,[RCX]; RET','conclusion':'MonoClass.element_class is first pointer (+0), v1 assumption is correct.'},
  {'function':'mono_class_instance_size','bytes':'8B 43 1C and 8B 41 1C','meaning':'MOV EAX,[RBX+0x1c] / MOV EAX,[RCX+0x1c] on both returned-size paths','conclusion':'MonoClass.instance_size is +28, not +144.'},
  {'function':'mono_array_element_size','bytes':'8B 83 90 00 00 00','meaning':'MOV EAX,[RBX+0x90]','conclusion':'Array MonoClass.element_size is +144; this is a distinct class field.'},
  {'function':'mono_class_value_size','bytes':'8B 73 1C then 83 EE 10','meaning':'MOV ESI,[RBX+0x1c]; SUB ESI,0x10','conclusion':'Unboxed value size is boxed instance_size minus16 for this installed runtime.'},
 ],
 'repair':'Read stride=arrayClass[144], boxed=elementClass[28], require stride==boxed-16 and existing16..128 boundary/alignment checks; reject mismatch. Never read elementClass[144] as instance_size.',
 'runtime_pin_enforced':True,'real_process_reads':0,
}
(HERE/'mono-layout-evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
print(json.dumps({'ok':True,'checks':7,'mono_sha256':digest,'offsets':{'element_class':0,'instance_size':28,'array_element_size':144,'object_header':16}}))
