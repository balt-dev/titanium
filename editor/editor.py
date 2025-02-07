import time
import imgui
from imgui.integrations.glfw import GlfwRenderer
import OpenGL.GL as gl
from pathlib import Path
from PIL import Image
import glfw
from dataclasses import dataclass, field
import tomllib
from typing import Self
import math
import uuid
import io

TOOLBAR_HEIGHT: int = 26

@dataclass
class Point:
    x: int = 0
    y: int = 0

    def __add__(self, other: Self) -> Self:
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Self) -> Self:
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, other: float) -> Self:
        return Point(self.x * other, self.y * other)

    def __truediv__(self, other: float) -> Self:
        return Point(self.x / other, self.y / other)

    def within(self, a: Self, b: Self) -> bool:
        return a.x <= self.x < b.x and a.y <= self.y < b.y

    @property
    def copy(self) -> Self:
        return Point(self.x, self.y)
    
    @property
    def tup(self) -> tuple[int, int]:
        return (self.x, self.y)

    def floor(self) -> Self:
        return Point(int(self.x), int(self.y))

@dataclass
class Element:
    name: str
    symbol: str
    pronouns: str
    authors: list[str]
    embed_color: int
    atomic_number: int | None
    coordinates: Point | None
    uuid: str = field(default_factory = uuid.uuid4)

CAMERA_DAMPING = 0.001
CAMERA_SPEED = 10000
ZOOM_EXP = 10000.0
ZOOM_DECAY = 0.99
EASING_TIME = 1

@dataclass
class Camera:
    pos: Point = field(default_factory = Point)
    vel: Point = field(default_factory = Point)
    accel: Point = field(default_factory = Point)
    zoom: float = 1
    target_zoom: float = 1

    last_pos: Point = field(default_factory = Point)
    last_dt: float = 0.01667
    easing_time: float = 0
    easing_start: Point | None = None
    easing_target: Point | None = None

    def ease_to(self, pos: Point):
        self.vel = Point()
        self.easing_time = 0
        self.easing_start = self.pos
        self.easing_target = pos

    def release_easing(self):
        if self.easing_target is None: return
        self.easing_target = None
        self.vel = (self.pos - self.last_pos) / self.last_dt

    def tick(self, dt: float):
        self.zoom += (self.target_zoom - self.zoom) * (1 - ZOOM_EXP ** (-ZOOM_DECAY * dt))
        self.last_pos = self.pos
        self.last_dt = dt
        if self.easing_target is not None:
            self.accel = Point()
            if self.easing_time > EASING_TIME:
                self.pos = self.easing_target
                self.easing_target = None
                self.easing_start = None
                return
            self.pos = self.easing_start + (self.easing_target - self.easing_start) * (1 - 2 ** (-10 * self.easing_time / EASING_TIME))
            self.easing_time += dt
            return
        self.pos += self.vel * dt
        self.vel += self.accel * dt
        self.vel *= CAMERA_DAMPING ** dt

@dataclass
class Table:
    image: int
    actual_image: Image.Image
    size: Point
    path: str
    elements: list[Element]

class Editor:
    tables: dict[str, Table]
    extras: list[(Element, str)]
    active_table: str
    active_element: Element | None

    @property
    def table(self):
        return self.tables[self.active_table]

    def __init__(self, window, impl):
        self.window = window
        self.impl = impl
        self.io = imgui.get_io()
        self.changed_since_save = False
        self.running = True
        self.tables = {}
        self.extras = []
        self.active_table = "normal"
        self.active_element = None
        self.camera = Camera()
        self.dragging = False
        self.was_dragging = False
        self.colorpicking = False


        # Load elements.toml
        with open("../elements.toml", "rb") as f:
            toml = tomllib.load(f)
        tex_ids = gl.glGenTextures(len(toml["tables"]))
        for (name, path), tex_id in zip(toml["tables"].items(), tex_ids):
            with Image.open(Path("..") / "elements" / path) as im:
                self.create_image(im, tex_id)
                self.tables[name] = Table (tex_id, im.convert("RGB"), Point(*im.size), path, [])
        del toml["tables"]
        
        for name, data in toml.items():
            coords = data.get("coordinates")
            if coords is not None:
                coords = Point(coords["x"], coords["y"])
            el = Element(
                name,
                data["symbol"],
                data["pronouns"],
                data["author"].split(", "),
                data["embed_color"],
                data.get("atomic_number"),
                coords
            )
            if "table" in data:
                self.tables[data["table"]].elements.append(el)
            else:
                self.extras.append((el, data["path"]))

        # Set keybinds

        glfw.set_key_callback(self.window, self.key_callback())

    def key_callback(self):
        def cb(window, key, scancode, action, mods):
            self.impl.keyboard_callback(window, key, scancode, action, mods)
            if self.io.want_text_input: return
            if key == glfw.KEY_UP or key == glfw.KEY_W:
                self.camera.accel.y = 0 if action == glfw.RELEASE else -CAMERA_SPEED / self.camera.zoom
                self.camera.release_easing()
            if key == glfw.KEY_LEFT or key == glfw.KEY_A:
                self.camera.accel.x = 0 if action == glfw.RELEASE else -CAMERA_SPEED / self.camera.zoom
                self.camera.release_easing()
            if key == glfw.KEY_DOWN or key == glfw.KEY_S:
                self.camera.accel.y = 0 if action == glfw.RELEASE else CAMERA_SPEED / self.camera.zoom 
                self.camera.release_easing()
            if key == glfw.KEY_RIGHT or key == glfw.KEY_D:
                self.camera.accel.x = 0 if action == glfw.RELEASE else CAMERA_SPEED / self.camera.zoom
                self.camera.release_easing()
            if key == glfw.KEY_COMMA and action == glfw.PRESS:
                self.move_to_el(-1)
            if key == glfw.KEY_PERIOD and action == glfw.PRESS:
                self.move_to_el(1)
            if key == glfw.KEY_SLASH and action == glfw.PRESS:
                self.move_to_el(0)
            if key == glfw.KEY_EQUAL and action == glfw.PRESS:
                self.camera.target_zoom *= 2
            if key == glfw.KEY_MINUS and action == glfw.PRESS:
                self.camera.target_zoom /= 2
            if key == glfw.KEY_BACKSLASH and action == glfw.PRESS:
                self.colorpicking = True
            if key == glfw.KEY_ENTER and action == glfw.PRESS:
                self.table.elements.append(Element(
                    "",
                    "",
                    "",
                    [],
                    0xFF0000,
                    None,
                    self.camera.pos
                ))
        return cb

    def move_to_el(self, offset: int):
        min_dist = math.inf
        min_el = None
        for i, el in enumerate(self.table.elements):
            diff = el.coordinates - (self.camera.pos if self.camera.easing_target is None else self.camera.easing_target)
            dist = math.sqrt(diff.x ** 2 + diff.y ** 2)
            if dist < min_dist:
                min_dist = dist
                min_el = i
        target_id = (min_el + offset) % len(self.table.elements)
        print(f"Closest to {min_el}, moving to {target_id}")
        target_el = self.table.elements[target_id]
        self.active_element = target_el
        self.camera.ease_to(target_el.coordinates + Point(24, 24))
    
    def main_loop(self, dt: float):
        self.camera.tick(dt)

        if glfw.window_should_close(self.window):
            self.running = False
            return
        glfw.poll_events()
        self.impl.process_inputs()

        imgui.new_frame()

        self.render_interface()
        
        gl.glClearColor(0., 0., 0., 1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        self.impl.render(imgui.get_draw_data())
        glfw.swap_buffers(self.window)

    def render_interface(self):
        width, height = self.io.display_size
        if imgui.begin_main_menu_bar():
            self.menu_bar()
            imgui.end_main_menu_bar()

        imgui.set_next_window_size(width, height - TOOLBAR_HEIGHT)
        imgui.set_next_window_position(0, TOOLBAR_HEIGHT)
        if imgui.begin(
            "Main", flags=
                imgui.WINDOW_NO_MOVE | 
                imgui.WINDOW_NO_COLLAPSE |
                imgui.WINDOW_NO_TITLE_BAR |
                imgui.WINDOW_NO_RESIZE |
                imgui.WINDOW_NO_BRING_TO_FRONT_ON_FOCUS
        ):
            imgui.push_style_var(imgui.STYLE_WINDOW_PADDING, (0, 0))
            self.main_interface()
            imgui.pop_style_var(imgui.STYLE_WINDOW_PADDING)
            imgui.end()

        if self.active_element and imgui.begin("Edit Element"):
            self.edit_interface()
            imgui.end()

    def create_image(self, im, tex_id):
        texture_data = im.convert("RGBA").tobytes()
        # Bind and set the texture at the id
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, im.size[0], im.size[1], 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, texture_data)

    def world_to_screen(self, coord: Point, size: Point) -> Point:
        return size / 2 - Point(self.camera.pos.x - coord.x,  self.camera.pos.y - coord.y) * self.camera.zoom

    def screen_to_world(self, coord: Point, size: Point) -> Point:
        return Point(self.camera.pos.x, self.camera.pos.y) - (size / 2 - coord) / self.camera.zoom

    def main_interface(self):
        screen_mouse = Point(*self.io.mouse_pos)
        main_size = Point(*imgui.get_content_region_available())
        world_mouse = self.screen_to_world(screen_mouse, main_size)

        if self.colorpicking and world_mouse.within(Point(), Point(*self.table.actual_image.size)):
            print(f"Mouse position: {world_mouse}")
            r, g, b = self.table.actual_image.getpixel((world_mouse.x, world_mouse.y)) 
            imgui.set_clipboard_text(f"#{r << 16 | g << 8 | b:06X}")
            self.colorpicking = False
        
        draw_list = imgui.get_window_draw_list()
        
        draw_list.add_image(
            self.table.image, 
            self.world_to_screen(Point(), main_size).tup,
            self.world_to_screen(self.table.size, main_size).tup,
        )

        just_started_dragging = False

        none_within = True

        for element in self.table.elements:
            top_left = element.coordinates + Point(0.5, 0.5)
            bottom_right = element.coordinates + Point(47.5, 47.5)
            within = world_mouse.within(top_left, bottom_right) and imgui.is_window_hovered()
            r, g, b = element.embed_color.to_bytes(3, "big")
            r, g, b = r / 255, g / 255, b / 255
            if self.camera.zoom > 1.01 and not within:
                draw_list.add_rect(
                    *self.world_to_screen(top_left, main_size).tup,
                    *self.world_to_screen(bottom_right, main_size).tup,
                    imgui.get_color_u32_rgba(0, 0, 0, 0.1),
                    thickness = self.camera.zoom
                )
                draw_list.add_rect(
                    *self.world_to_screen(top_left, main_size).tup,
                    *self.world_to_screen(bottom_right, main_size).tup,
                    imgui.get_color_u32_rgba(1, 1, 1, 0.1),
                    thickness = self.camera.zoom
                )
                draw_list.add_rect(
                    *self.world_to_screen(top_left, main_size).tup,
                    *self.world_to_screen(bottom_right, main_size).tup,
                    imgui.get_color_u32_rgba(r, g, b, 0.6),
                    thickness = self.camera.zoom
                )
            if within:
                none_within = False
                tl = top_left - Point(1, 1)
                br = bottom_right + Point(1, 1)
                draw_list.add_rect_filled(
                    *self.world_to_screen(tl, main_size).tup,
                    *self.world_to_screen(br, main_size).tup,
                    imgui.get_color_u32_rgba(1, 1, 1, 0.2),
                )
                draw_list.add_rect(
                    *self.world_to_screen(tl, main_size).tup,
                    *self.world_to_screen(br, main_size).tup,
                    imgui.get_color_u32_rgba(r, g, b, 1),
                    thickness = self.camera.zoom
                )
                if imgui.is_mouse_clicked():
                    self.active_element = element
                if imgui.is_mouse_clicked(1) and not self.was_dragging:
                    self.active_element = element
                    self.dragging = True
                    self.drag_offset = element.coordinates - world_mouse
                    just_started_dragging = True
        if imgui.is_window_hovered() and imgui.is_mouse_clicked() and none_within:
            self.active_element = None
        self.was_dragging = self.dragging
        if self.dragging and not just_started_dragging:
            if self.active_element is None or imgui.is_mouse_clicked(1):
                self.dragging = False
            else:
                self.active_element.coordinates = (world_mouse + self.drag_offset).floor()

    def edit_interface(self):
        changed, new_name = imgui.input_text(f"Name##{self.active_element.uuid}", self.active_element.name)
        if changed: self.active_element.name = new_name
        old_symbol = self.active_element.symbol
        for a, b in zip("₀₁₂₃₄₅₆₇₈₉•×", "0123456789+@"):
            old_symbol = old_symbol.replace(a, b)
        changed, new_symbol = imgui.input_text(f"Symbol##{self.active_element.uuid}", old_symbol)
        if changed: 
            for a, b in zip("₀₁₂₃₄₅₆₇₈₉•×", "0123456789+@"):
                new_symbol = new_symbol.replace(b, a)
            self.active_element.symbol = new_symbol
        changed, new_pronouns = imgui.input_text(f"Pronouns##{self.active_element.uuid}", self.active_element.pronouns)
        if changed: self.active_element.pronouns = new_pronouns
        r, g, b = self.active_element.embed_color.to_bytes(3, "big")
        changed, new_color = imgui.color_edit3(f"Embed Color##{self.active_element.uuid}", r / 255, g / 255, b / 255)
        if changed:
            r, g, b = new_color
            new_int = int(r * 255) << 16 | int(g * 255) << 8 | int(b * 255)
            self.active_element.embed_color = new_int
        if imgui.checkbox("Atomic Number", self.active_element.atomic_number is not None)[1]:
            if self.active_element.atomic_number is None:
                self.active_element.atomic_number = 0
            imgui.same_line()
            changed, new_number = imgui.input_int(f"##Atomic Number##{self.active_element.uuid}", self.active_element.atomic_number)
            if changed: self.active_element.atomic_number = new_number
        else:
            self.active_element.atomic_number = None

        imgui.text(f"Authors")
        imgui.indent()
        author_list = []
        for i, author in enumerate(self.active_element.authors):
            changed, new_name = imgui.input_text(f"##{self.active_element.uuid}.{i}.author", author)
            if changed: author = new_name
            imgui.same_line()
            if not imgui.button(f"-##{self.active_element.uuid}.{i}"):
                author_list.append(author)

        if imgui.button("+"):
            author_list.append("")
        self.active_element.authors = author_list
        imgui.unindent()

        imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.0, 0.0, 1.0)
        imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.8, 0.4, 0.4, 1.0)
        imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, 0.4, 0.0, 0.0, 1.0)
        if imgui.button("Remove"):
            remove_id = None
            for i, el in enumerate(self.table.elements):
                if el.uuid == self.active_element.uuid:
                    remove_id = i
                    self.active_element = None
                    break
            del self.table.elements[remove_id]
        imgui.pop_style_color(3)
    
    def save(self):
        toml = io.StringIO()
        toml.write(f"[tables]\n")
        for table, table_data in self.tables.items():
            toml.write(f'{table} = "{table_data.path}"\n')
        for table, table_data in self.tables.items():
            toml.write(f"\n### {table} ###\n\n\n")
            for element in table_data.elements:
                toml.write(f'["{element.name}"]\n')
                toml.write(f'table = "{table}"\n')
                toml.write(f'symbol = "{element.symbol}"\n')
                toml.write(f'pronouns = "{element.pronouns}"\n')
                toml.write(f'author = "{", ".join(element.authors)}"\n')
                toml.write(f'embed_color = 0x{element.embed_color:06X}\n')
                toml.write(f'coordinates = {{ x = {element.coordinates.x}, y = {element.coordinates.y} }}\n')
                if element.atomic_number is not None:
                    toml.write(f'atomic_number = {element.atomic_number}\n')
                toml.write(f'\n')
        toml.write(f"\n### extras ###\n\n\n")
        for (element, path) in self.extras:
            toml.write(f'["{element.name}"]\n')
            toml.write(f'symbol = "{element.symbol}"\n')
            toml.write(f'pronouns = "{element.pronouns}"\n')
            toml.write(f'author = "{", ".join(element.authors)}"\n')
            toml.write(f'embed_color = 0x{element.embed_color:06X}\n')
            if element.atomic_number is not None:
                toml.write(f'atomic_number = {element.atomic_number}\n')
            toml.write(f'path = "{path}"\n')
            toml.write(f'\n')
        # We only do this now so that the toml isn't wiped out if something errors mid-write
        with open("../elements.toml", "w") as f:
            f.write(toml.getvalue())

    def menu_bar(self):
        if imgui.button("Save"):
            self.save()
        imgui.text("|")
        imgui.push_style_color(imgui.COLOR_BUTTON, 0.0, 0.0, 0.0, 0.0)
        imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 1.0, 1.0, 1.0, 0.3)
        imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, 1.0, 1.0, 1.0, 0.1)
        imgui.push_style_var(imgui.STYLE_ITEM_SPACING, (0.0, 0.0))
        for table in self.tables:
            if "gender" in table: continue
            if imgui.button(table):
                self.active_element = None
                self.active_table = table
                if len(self.tables[table].elements):
                    self.camera.ease_to(self.tables[table].elements[0].coordinates.copy)
                self.camera.vel = Point()
                self.camera.target_zoom = 4
        imgui.pop_style_var(1)
        imgui.pop_style_color(3)