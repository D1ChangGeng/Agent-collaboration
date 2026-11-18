#define _GNU_SOURCE
#include <linux/input-event-codes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>
#include "virtual-keyboard-client.h"

struct keyboard_connection {
    struct wl_seat *seat;
    struct zwp_virtual_keyboard_manager_v1 *manager;
};

static void register_global(void *data, struct wl_registry *registry, uint32_t name,
                            const char *interface, uint32_t version)
{
    (void)version;
    struct keyboard_connection *connection = data;
    if (strcmp(interface, "wl_seat") == 0 && !connection->seat)
        connection->seat = wl_registry_bind(registry, name, &wl_seat_interface, 1);
    if (strcmp(interface, "zwp_virtual_keyboard_manager_v1") == 0)
        connection->manager = wl_registry_bind(
            registry, name, &zwp_virtual_keyboard_manager_v1_interface, 1);
}

static void unregister_global(void *data, struct wl_registry *registry, uint32_t name)
{
    (void)data;
    (void)registry;
    (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = register_global,
    .global_remove = unregister_global,
};

static int lookup_key(const char *name)
{
    const struct { const char *name; int code; } keys[] = {
        {"alt", KEY_LEFTALT}, {"ctrl", KEY_LEFTCTRL}, {"shift", KEY_LEFTSHIFT},
        {"Tab", KEY_TAB}, {"Escape", KEY_ESC}, {"Return", KEY_ENTER},
        {"KP_Enter", KEY_KPENTER}, {"Down", KEY_DOWN}, {"Up", KEY_UP},
        {"space", KEY_SPACE}, {"BackSpace", KEY_BACKSPACE},
        {"0", KEY_0}, {"a", KEY_A}, {"t", KEY_T}, {"v", KEY_V},
    };
    for (size_t i = 0; i < sizeof(keys) / sizeof(keys[0]); ++i)
        if (strcmp(keys[i].name, name) == 0)
            return keys[i].code;
    return -1;
}

static void send_key(struct zwp_virtual_keyboard_v1 *keyboard, struct xkb_state *state,
                     int code, enum xkb_key_direction direction)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    uint32_t milliseconds = (uint32_t)((uint64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000);
    zwp_virtual_keyboard_v1_key(keyboard, milliseconds, code, direction == XKB_KEY_DOWN);
    xkb_state_update_key(state, code + 8, direction);
    zwp_virtual_keyboard_v1_modifiers(
        keyboard,
        xkb_state_serialize_mods(state, XKB_STATE_MODS_DEPRESSED),
        xkb_state_serialize_mods(state, XKB_STATE_MODS_LATCHED),
        xkb_state_serialize_mods(state, XKB_STATE_MODS_LOCKED),
        xkb_state_serialize_layout(state, XKB_STATE_LAYOUT_EFFECTIVE));
}

static int copy_keymap(const char *text, size_t size)
{
    int fd = memfd_create("porpita-validation-keymap", MFD_CLOEXEC);
    if (fd < 0)
        return -1;
    if (ftruncate(fd, (off_t)size) != 0) {
        close(fd);
        return -1;
    }
    void *memory = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (memory == MAP_FAILED) {
        close(fd);
        return -1;
    }
    memcpy(memory, text, size);
    munmap(memory, size);
    return fd;
}

int main(int argc, char **argv)
{
    const char *run = getenv("PORPITA_NATIVE_RUN");
    const char *runtime = getenv("XDG_RUNTIME_DIR");
    const char *socket = getenv("WAYLAND_DISPLAY");
    if (argc < 2 || argc > 5 || !run || !runtime || strncmp(run, "/tmp/porpita-ui", 15) != 0 ||
        strncmp(runtime, run, strlen(run)) != 0 || strcmp(runtime + strlen(run), "/runtime") != 0 ||
        !socket || strncmp(socket, "wayland-", 8) != 0 || !socket[8] ||
        strspn(socket + 8, "0123456789") != strlen(socket + 8) || getenv("DISPLAY")) {
        fputs("Expected an isolated Porpita Wayland session and one key or chord.\n", stderr);
        return 2;
    }
    int codes[4];
    for (int i = 1; i < argc; ++i) {
        codes[i - 1] = lookup_key(argv[i]);
        if (codes[i - 1] < 0) {
            fprintf(stderr, "Unsupported validation key: %s\n", argv[i]);
            return 2;
        }
    }

    struct wl_display *display = wl_display_connect(NULL);
    if (!display) {
        perror("Wayland connection");
        return 1;
    }
    struct keyboard_connection connection = {0};
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, &connection);
    if (wl_display_roundtrip(display) < 0 || !connection.seat || !connection.manager) {
        fputs("The isolated compositor did not advertise its virtual keyboard.\n", stderr);
        wl_display_disconnect(display);
        return 1;
    }

    struct xkb_context *context = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    if (!context)
        return 1;
    struct xkb_rule_names names = { .rules = "evdev", .model = "pc105", .layout = "us" };
    struct xkb_keymap *keymap = xkb_keymap_new_from_names(context, &names, XKB_KEYMAP_COMPILE_NO_FLAGS);
    if (!keymap)
        return 1;
    struct xkb_state *state = xkb_state_new(keymap);
    char *text = xkb_keymap_get_as_string(keymap, XKB_KEYMAP_FORMAT_TEXT_V1);
    if (!state || !text)
        return 1;
    size_t size = strlen(text) + 1;
    int fd = copy_keymap(text, size);
    if (fd < 0) {
        perror("Wayland keymap");
        return 1;
    }

    struct zwp_virtual_keyboard_v1 *keyboard =
        zwp_virtual_keyboard_manager_v1_create_virtual_keyboard(connection.manager, connection.seat);
    zwp_virtual_keyboard_v1_keymap(keyboard, XKB_KEYMAP_FORMAT_TEXT_V1, fd, (uint32_t)size);
    close(fd);
    if (wl_display_roundtrip(display) < 0)
        return 1;
    for (int i = 0; i < argc - 1; ++i)
        send_key(keyboard, state, codes[i], XKB_KEY_DOWN);
    for (int i = argc - 2; i >= 0; --i)
        send_key(keyboard, state, codes[i], XKB_KEY_UP);
    int result = wl_display_roundtrip(display) < 0 ? 1 : 0;
    zwp_virtual_keyboard_v1_destroy(keyboard);
    wl_display_disconnect(display);
    xkb_state_unref(state);
    xkb_keymap_unref(keymap);
    xkb_context_unref(context);
    free(text);
    return result;
}
