#!../.venv/bin/python
import ctypes
import sys
import traceback
import imgui
import glfw
from imgui.integrations.glfw import GlfwRenderer
import OpenGL.GL as gl
from pathlib import Path
import os
from editor import Editor
import time

def main():
    window = init()
    imgui.create_context()
    impl = GlfwRenderer(window)
    impl.refresh_font_texture()
    editor = Editor(window, impl)
    try:
        last_update = time.perf_counter()
        dt = 1 / 60
        while editor.running:
            editor.main_loop(dt)
            new_time = time.perf_counter()
            dt = new_time - last_update
            last_update = new_time
            if dt < 1 / 60:
                time.sleep(1 / 60 - dt)
    except Exception:  # Don't catch KeyboardInterrupt
        print("[FATAL EXCEPTION]")
        with open(Path(__file__).resolve().parent / "crashlog.txt", "w+") as f:
            f.write(traceback.format_exc())
        traceback.print_exc()
        if sys.gettrace() is not None:  # only reraise if not being debugged
            raise
    finally:
        editor.impl.shutdown()
        glfw.terminate()

WIDTH, HEIGHT = 1366, 768
WINDOW_NAME = "elements.toml editor"

def init():
    if not glfw.init():
        print("Could not initialize OpenGL context")
        sys.exit(1)

    # OS X supports only forward-compatible core profiles from 3.2
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)

    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, gl.GL_TRUE)

    # Create a windowed mode window and its OpenGL context
    window = glfw.create_window(WIDTH, HEIGHT, WINDOW_NAME, None, None)
    glfw.make_context_current(window)

    if not window:
        glfw.terminate()
        print("Could not initialize Window")
        sys.exit(1)

    return window


if __name__ == '__main__':
    main()