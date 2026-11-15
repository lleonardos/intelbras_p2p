/* ABI recovered statically from Libt2uWrapper.dll; no SIM Next executable used. */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef void (__cdecl *init_fn)(const char *, unsigned short, const char *);
typedef int (__cdecl *add_fn)(const char *, const char *, const char *, unsigned short, unsigned short);
/* Status calls: signatures and return codes observed against real recorders, not documented.
   t2u_status: 0 connecting, 1 connected to the server, -2 server key refused.
   t2u_port_status: 0 connecting, 1 tunnel connected, -4 device offline or unknown, -5 password refused.
   t2u_query: 1 device online, 0 offline or unknown, -1 no answer from the server. */
typedef int (__cdecl *status_fn)(void);
typedef int (__cdecl *port_status_fn)(unsigned short, void *);
typedef int (__cdecl *query_fn)(const char *, void *);
/* The SDK polls from dozens of threads with Sleep(1) and 1 ms multimedia timers. Wine honours those
   literally and every wake-up costs a wineserver round trip, which kept about one CPU core busy per
   recorder. Stretching the short waits cut that by roughly 85% with no video packets lost in tests with
   eight main streams. T2U_MIN_WAIT_MS overrides the floor; 0 leaves the SDK untouched. */
typedef UINT (WINAPI *timer_fn)(UINT, UINT, void *, DWORD_PTR, UINT);
static DWORD min_wait_ms = 30;
static timer_fn real_timer;
static VOID WINAPI slow_sleep(DWORD ms) {
    Sleep(ms && ms < min_wait_ms ? min_wait_ms : ms);
}
static UINT WINAPI slow_timer(UINT delay, UINT resolution, void *callback, DWORD_PTR user, UINT flags) {
    return real_timer(delay < min_wait_ms ? min_wait_ms : delay, resolution, callback, user, flags);
}
/* Point every import-table slot of `module` that holds `from` at `to`. */
static void redirect(HMODULE module, void *from, void *to) {
    BYTE *base = (BYTE *)module;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY imports = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!from || !imports.VirtualAddress) return;
    for (IMAGE_IMPORT_DESCRIPTOR *d = (IMAGE_IMPORT_DESCRIPTOR *)(base + imports.VirtualAddress); d->Name; d++)
        for (void **slot = (void **)(base + d->FirstThunk); *slot; slot++)
            if (*slot == from) {
                DWORD protection;
                if (!VirtualProtect(slot, sizeof *slot, PAGE_READWRITE, &protection)) continue;
                *slot = to;
                VirtualProtect(slot, sizeof *slot, protection, &protection);
            }
}
static void slow_short_waits(HMODULE dll) {
    const char *setting = getenv("T2U_MIN_WAIT_MS");
    if (setting && *setting) min_wait_ms = (DWORD)strtoul(setting, NULL, 10);
    if (!min_wait_ms) return;
    redirect(dll, (void *)GetProcAddress(GetModuleHandleA("kernel32.dll"), "Sleep"), (void *)slow_sleep);
    HMODULE winmm = LoadLibraryA("winmm.dll");
    real_timer = winmm ? (timer_fn)GetProcAddress(winmm, "timeSetEvent") : NULL;
    redirect(dll, (void *)real_timer, (void *)slow_timer);
}
static const char *required(const char *name) {
    const char *v = getenv(name);
    if (!v || !*v) { fprintf(stderr, "Missing setting: %s\n", name); exit(2); }
    return v;
}
static unsigned short port(const char *name) {
    char *end;
    long v = strtol(required(name), &end, 10);
    if (*end || v < 1 || v > 65535) { fprintf(stderr, "Invalid port: %s\n", name); exit(2); }
    return (unsigned short)v;
}
int main(int argc, char **argv) {
    const char *directory = getenv("T2U_DLL_DIR");
    if (!directory) directory = "Z:\\run\\bridge\\sdk";
    char dll_path[MAX_PATH];
    if (snprintf(dll_path, sizeof(dll_path), "%s\\libt2u.dll", directory) >= MAX_PATH) return 2;
    SetDllDirectoryA(directory);
    HMODULE dll = LoadLibraryA(dll_path);
    if (!dll) { fprintf(stderr, "Cannot load libt2u.dll: %lu\n", GetLastError()); return 3; }
    init_fn init = (init_fn)GetProcAddress(dll, "t2u_init");
    add_fn add = (add_fn)GetProcAddress(dll, "t2u_add_port_v3");
    if (!init || !add) return 4;
    if (argc == 2 && strcmp(argv[1], "--check-load") == 0) {
        puts("DLL loaded; required exports present. No network initialization performed.");
        return 0;
    }
    /* Validate every setting before the SDK touches the network. */
    const char *server = required("T2U_SERVER"), *key = required("T2U_SERVER_KEY");
    const char *uuid = required("T2U_UUID"), *remote_ip = required("T2U_REMOTE_IP");
    const char *password = getenv("T2U_PASSWORD");
    unsigned short server_port = port("T2U_SERVER_PORT"), remote_port = port("T2U_REMOTE_PORT");
    unsigned short local_port = port("T2U_LOCAL_PORT");
    slow_short_waits(dll);
    init(server, server_port, key);
    int result = add(uuid, password ? password : "", remote_ip, remote_port, local_port);
    if (getenv("T2U_HTTP_LOCAL")) {
        add(uuid, password ? password : "", remote_ip, port("T2U_HTTP_REMOTE"), port("T2U_HTTP_LOCAL"));
    }
    printf("t2u_add_port_v3 returned %d; stream readiness is checked separately\n", result);
    fflush(stdout);
    /* Report "server port query" codes to a file whenever they change; the bridge turns them into
       log messages. Only numbers are written, never identifiers. */
    status_fn status = (status_fn)GetProcAddress(dll, "t2u_status");
    port_status_fn port_status = (port_status_fn)GetProcAddress(dll, "t2u_port_status");
    query_fn query = (query_fn)GetProcAddress(dll, "t2u_query");
    const char *status_file = getenv("T2U_STATUS_FILE");
    if (!status || !port_status || !query || !status_file) for (;;) Sleep(INFINITE);
    int last[3] = {-99, -99, -99};
    for (;;) {
        /* The SDK fills an undocumented structure here (85 bytes observed); give it ample room. */
        unsigned char scratch[512];
        memset(scratch, 0, sizeof scratch);
        int now[3] = {status(), port_status(local_port, scratch), 1};
        if (now[1] != 1) {
            memset(scratch, 0, sizeof scratch);
            now[2] = query(uuid, scratch);
        }
        if (memcmp(now, last, sizeof now) != 0) {
            FILE *out = fopen(status_file, "w");
            if (out) {
                fprintf(out, "%d %d %d\n", now[0], now[1], now[2]);
                fclose(out);
                memcpy(last, now, sizeof now);
            }
        }
        Sleep(1000);
    }
}
