// V2: current-runtime disk-export evidence corrects instance_size to28 and
// separately verifies array element_size144. See mono-layout-evidence.json.
// Other explanatory source comments below are inherited from the MIT upstream.
// Struct offsets for the Mono runtime Unity ships, x64.
//
// These are NOT magic numbers and they are NOT copied from any tool: each is the
// byte offset of a named field in a public Mono struct (Unity-Technologies/mono,
// headers metadata-internals.h / class-internals.h / domain-internals.h /
// mono-internal-hash.h) compiled for 64-bit. They are stable across Hearthstone
// content patches - only a Unity ENGINE upgrade can move them, at which point the
// values below are re-derived from the same headers (see docs/OFFSETS.md).
//
// Verified against the Unity 2022.3 / 6000.3 Mono fork Hearthstone uses in 2026.

namespace Bgtracker.Msync
{
    internal static class Off
    {
        // MonoDomain (domain-internals.h)
        public const int DomainAssemblies = 160;   // GSList *domain_assemblies

        // MonoAssembly -> MonoImage (metadata-internals.h)
        public const int AssemblyImage = 96;        // MonoImage *image

        // MonoImage.class_cache is a MonoInternalHashTable embedded in the image.
        public const int ImageClassCache = 1232;    // offset of class_cache in MonoImage
        public const int HashTableSize = 24;        // MonoInternalHashTable.size
        public const int HashTableTable = 32;       // MonoInternalHashTable.table (MonoClass**)

        // MonoClass / MonoClassDef / MonoClassRuntimeInfo / MonoVTable (class-internals.h)
        public const int ClassKind = 27;            // low 3 bits: 1=Def 3=GInst (class_kind)
        public const int ClassGenericClass = 240;   // MonoGenericClass* on a generic-inst class
        public const int ClassParent = 48;          // MonoClass *parent
        public const int ClassName = 72;            // const char *name
        public const int ClassNamespace = 80;       // const char *name_space
        public const int ClassVTableSize = 92;      // int vtable_size
        // Current installed Mono export mono_class_instance_size loads [class+0x1c].
        // Upstream 144 conflated instance_size with array-class element_size.
        // See mono-layout-evidence.json (disk PE export bytes, no process access).
        public const int ClassInstanceSize = 28;    // int instance_size, includes object header
        public const int ClassArrayElementSize = 144; // array-class element_size, mono_array_element_size
        public const int ClassFields = 152;         // MonoClassField *fields
        public const int ClassRuntimeInfo = 208;    // MonoClassRuntimeInfo *runtime_info
        public const int ClassFieldCount = 256;     // int field.count (MonoClassDef)
        public const int ClassNextInCache = 264;    // MonoClass *next_class_cache (MonoClassDef)
        public const int RuntimeInfoDomainVtables = 8;  // MonoVTable *domain_vtables[]
        public const int VTableData = 72;           // gpointer vtable[] - static store follows

        // MonoClassField (metadata-internals.h): { MonoType *type; const char *name;
        //                                          MonoClass *parent; int offset; }
        public const int FieldSize = 32;            // sizeof(MonoClassField), 8-aligned
        public const int FieldName = 8;             // const char *name
        public const int FieldOffsetValue = 24;     // int offset (== IntPtr.Size * 3)

        // MonoString { MonoObject obj; int length; wchar chars[]; } - obj header is
        // 16 bytes on x64, so chars begin at 20.
        public const int UnicodeString = 20;        // offset of the UTF-16 char data
    }
}
