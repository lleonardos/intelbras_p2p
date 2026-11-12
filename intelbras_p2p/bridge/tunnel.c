/* ABI recovered statically from Libt2uWrapper.dll; no SIM Next executable used. */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef void (__cdecl *init_fn)(const char *, unsigned short, const char *);
typedef int (__cdecl *add_fn)(const char *, const char *, const char *, unsigned short, unsigned short);
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
    init(server, server_port, key);
    int result = add(uuid, password ? password : "", remote_ip, remote_port, local_port);
    printf("t2u_add_port_v3 returned %d; stream readiness is checked separately\n", result);
    fflush(stdout);
    /* Return-code semantics are not yet established. Do not label this connected. */
    for (;;) Sleep(INFINITE);
}
