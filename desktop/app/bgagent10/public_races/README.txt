PublicRaces.exe v2 — isolated read-only public lobby races helper, x64 .NET Framework.

V2 fixes the observed "Invalid service Entry stride": upstream offset144 was
array-class element_size, not boxed value-class instance_size. Current on-disk
Mono exports prove element_class+0, instance_size+28, array element_size+144,
and unboxed value size=instance_size-16. Both independent sizes must agree;
original bounds16..128 are retained. Exact installed Mono SHA is now enforced.
See mono-layout-evidence.json and audit_mono_disk.py for reproducible bytes/RVAs.

CLI (all four arguments required; no auto-process selection):
PublicRaces.exe --pid PID --expected-exe ABSOLUTE_HEARTHSTONE_EXE --expected-build 255790 --expected-start-ticks UTC_DOTNET_TICKS
process_start_ticks is DateTime UTC ticks since 0001-01-01. Windows FILETIME ticks + 504911232000000000.
One JSON line on stdout. Success exit0; any blocked/unready result exit2.
--self-test runs only fake byte-addressed memory and does not attach to a process.

Success schema (illustrative names/types ONLY; not a claimed real-client sample):
{
  "ok": true,
  "pid": 123,
  "process_start_ticks": 639000000000000000,
  "client_build": "255790",
  "game_state_id": "0xINSTANCE",
  "game_entity_id": "0xINSTANCE",
  "game_entity_instance_id": "0xINSTANCE",
  "game_entity_id_kind": "instance_pointer_not_network_entity_id",
  "game_uuid": "optional-client-uuid-or-null",
  "create_game_phase": 2,
  "game_over": false,
  "race_ids": [11,17,126],
  "race_list_version": 7,
  "source_field": "GameState.s_instance.m_availableRacesInBattlegroundsExcludingAmalgam",
  "network_game_id": 30223,
  "network_client_id": 130382848,
  "network_source_field": "Network.m_state.LastGameServerInfo.GameHandle/ClientHandle",
  "source_assembly_sha256": "2408c5eae3d5ab083b8b290a7278147159e79a3c6e72e1d922ef44028ed16afb"
}

Failure schema: {"ok":false,"retryable":true|false,"error":"Type: exact reason"}.
retryable true: no active singleton/runtime/races/Network service/connection yet,
CREATING or already ended, list/service/game/connection changed mid-read, short RPM.
retryable false: unsupported build/file hash/process identity, invalid pointer/count,
unknown/INVALID/ALL/duplicate race, missing known field, unsupported Mono root code/layout.
The caller should bound retries, obey stop, and never treat retries as known empty/zero.

Required bridge acceptance (owned by root):
- Read/anchor the actual current Power.log game and connection evidence before and after.
- Exact network_game_id and network_client_id must match the latest current-session
  GameNetLogger Network.GotoGameServe line (and expected process creation/PID).
- Do not identify a game solely by GameEntity entity number, timestamp, turn, instance pointer,
  or nullable Uuid; game_entity_id here is explicitly an INSTANCE pointer, not protocol EntityID.
- New CREATE_GAME/process/connection invalidates all cached races. No success can be reused
  across a different anchored game even when pointers or list versions happen to repeat.
- Require nonterminal BG mode/log build255790 and model/card build255130 separately.
- This helper only returns exact public race IDs. Caller maps complete public list into
  the fixed 11 flags and preserves source proof. Unknown is not a zero flag.

Compilation: .\build.ps1 uses installed Framework64\v4.0.30319\csc.exe /platform:x64.
No NuGet packages, SDK, elevated privileges, injection, writes, inputs, log writes or captures.
Only OpenProcess VM_READ|QUERY_INFORMATION, ReadProcessMemory, CloseHandle are imported.

Offline evidence: 5 grouped fake tests; exact source metadata pinned on disk.
NOT VERIFIED: real-client attachment, runtime initialization/public-list timing,
remaining service dictionary layout, or end-to-end current-log binding. The four
specific corrected size/element/header offsets are proved from this installed DLL,
not inferred from fake fixtures. Other offsets retain their existing source basis.
They remain user-owned real-client acceptance. Fail closed on changed Unity/assembly.
Model/rules target remains255130; this auxiliary reader is authorized client255790 only.
