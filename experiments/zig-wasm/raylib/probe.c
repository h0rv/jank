/* AI-assisted bounded raylib/raygui interop probe. */
#include <stdio.h>
#include "raylib.h"
#include "raygui.h"
#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#endif

static int frames, keyPresses, buttonClicks;
static void frame(void)
{
    if (IsKeyPressed(KEY_SPACE)) printf("KEY SPACE: state=%d\n", ++keyPresses);
    BeginDrawing();
    ClearBackground(RAYWHITE);
    DrawRectangle(10, 10, 80, 80, keyPresses ? GREEN : MAROON);
    DrawCircle(260, 55, 30, BLUE);
    DrawText("raylib 6.0 + raygui 5.0 / memory64", 10, 110, 18, BLACK);
    DrawText("SPACE changes the square", 10, 140, 18, DARKGRAY);
    if (GuiButton((Rectangle){ 10, 180, 180, 35 }, "Click raygui button"))
        printf("GUI BUTTON: state=%d\n", ++buttonClicks);
    EndDrawing();
    ++frames;
#ifdef __EMSCRIPTEN__
    EM_ASM({ window.probeFrame($0, $1, $2); }, frames, keyPresses, buttonClicks);
#endif
}

int main(void)
{
    InitWindow(480, 250, "raylib + raygui probe");
    if (!IsWindowReady()) return 1;
#ifdef __EMSCRIPTEN__
    emscripten_set_main_loop(frame, 0, 0);
#else
    SetTargetFPS(60);
    while (!WindowShouldClose()) frame();
    CloseWindow();
#endif
    return 0;
}
