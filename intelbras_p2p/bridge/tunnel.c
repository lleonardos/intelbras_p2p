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
    init(required("T2U_SERVER"), (unsigned short)atoi(required("T2U_SERVER_PORT")), required("T2U_SERVER_KEY"));
    int result = add(required("T2U_UUID"), getenv("T2U_PASSWORD") ? getenv("T2U_PASSWORD") : "", required("T2U_REMOTE_IP"), (unsigned short)atoi(required("T2U_REMOTE_PORT")), (unsigned short)atoi(required("T2U_LOCAL_PORT")));
    printf("t2u_add_port_v3 returned %d; stream readiness is checked separately\n", result);
    fflush(stdout);
    /* Return-code semantics are not yet established. Do not label this connected. */
    for (;;) Sleep(1000);
}
