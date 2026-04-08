import time
import board
import displayio
import terminalio
from adafruit_display_text import label
from adafruit_funhouse import FunHouse
from adafruit_io.adafruit_io import IO_HTTP
import os
import ssl
import wifi
import socketpool
import adafruit_requests
import supervisor
supervisor.runtime.autoreload = False

# ---------------------------
# GET CREDENTIALS FROM ENV
# ---------------------------
ssid     = os.getenv("CIRCUITPY_WIFI_SSID")
password = os.getenv("CIRCUITPY_WIFI_PASSWORD")
io_uid   = os.getenv("ADAFRUIT_AIO_USERNAME")
io_key   = os.getenv("ADAFRUIT_AIO_KEY")

# ---------------------------
# CONNECT WIFI
# ---------------------------
print("Connecting to WiFi", ssid)
wifi.radio.connect(ssid, password)
print("Connected! IP:", wifi.radio.ipv4_address)

pool        = socketpool.SocketPool(wifi.radio)
ssl_context = ssl.create_default_context()
requests    = adafruit_requests.Session(pool, ssl_context)
io          = IO_HTTP(io_uid, io_key, requests)

# ---------------------------
# IO FEEDS
# ---------------------------
print("Loading feeds...")
energy_feed   = io.get_feed("energy")
temp_feed     = io.get_feed("temperature")
humidity_feed = io.get_feed("humidity")
mind_feed     = io.get_feed("mind")
body_feed     = io.get_feed("body")
soul_feed     = io.get_feed("soul")
print("Feeds loaded.")

# ---------------------------
# INIT FUNHOUSE
# ---------------------------
funhouse = FunHouse(default_bg=0x000000)
display  = board.DISPLAY

# ---------------------------
# BIRD FRAMES
# ---------------------------
BIRD_RIGHT = (
    "  __//    \n"
    " /.__.\\ \n"
    " \\ \\/ /  \n"
    " /    \\__ \n"
    "(      -/  \n"
    " \\_____/  \n"
    "    | |    \n"
    "---\"-\"---"
)
BIRD_FRONT = (
    "  _//_    \n"
    " /.__.\\ \n"
    " \\ \\/ /  \n"
    "__/    \\__\n"
    "\\-      -/\n"
    " \\______/ \n"
    "   |  |   \n"
    "--\"-\"----"
)
BIRD_LEFT = (
    "    \\\\__  \n"
    "  /.__.\\ \n"
    "  \\ \\/ / \n"
    "__/    \\  \n"
    " \\-      )\n"
    "  \\_____/ \n"
    "    | |   \n"
    "---\"-\"---"
)
BIRD_SLEEP = (
    "  _//_    \n"
    " /.-.-.\\ \n"
    " \\ \\/ /  \n"
    "__/    \\__\n"
    "\\-      -/\n"
    " \\______/ \n"
    "   |  |   \n"
    "--\"-\"----"
)

BIRD_DANCE = [BIRD_LEFT, BIRD_FRONT, BIRD_RIGHT, BIRD_FRONT]

# ---------------------------
# STATE MACHINE
# ---------------------------
STATE_ACTIVE  = "ACTIVE"
STATE_LOGGING = "LOGGING"
STATE_SLEEP   = "SLEEP"

state                 = STATE_ACTIVE
last_interaction_time = time.monotonic()
SLEEP_TIMEOUT         = 60

# ---------------------------
# SLEEP ANIMATION
# ---------------------------
sleep_bob_dir   = 1
last_sleep_time = 0.0
SLEEP_DELAY     = 1.2

# ---------------------------
# TOUCH PAD CONFIG
# Left=Body, Mid=Mind, Right=Soul
# ---------------------------
MAX_VAL        = 5
last_touch      = [False, False, False]
last_touch_time = [0.0, 0.0, 0.0]
TOUCH_DEBOUNCE  = 0.3

def cycle_value(current):
    return (current + 1) % (MAX_VAL + 1)

def draw_mbs_bar(value, max_val=5):
    return "[" + ("#" * value) + ("-" * (max_val - value)) + "]"

# ---------------------------
# MIND / BODY / SOUL VALUES
# ---------------------------
mind_val = 0
body_val = 0
soul_val = 0

# ---------------------------
# SUBMISSION COOLDOWN
# ---------------------------
SUBMIT_COOLDOWN  = 45
last_submit_time = -SUBMIT_COOLDOWN

# ---------------------------
# UI GROUPS
# ---------------------------
main_group = displayio.Group()
display.root_group = main_group

bird_label    = label.Label(
    terminalio.FONT,
    text=BIRD_FRONT,
    x=85, y=10,
    color=0x069494,
    line_spacing=1.0
)
energy_label  = label.Label(terminalio.FONT, text="Energy: 0 [----------]", x=10, y=125, color=0xFFD700)
body_label    = label.Label(terminalio.FONT, text="Body: [-----]",           x=10, y=140, color=0xFF6B6B)
mind_label    = label.Label(terminalio.FONT, text="Mind: [-----]",           x=10, y=155, color=0x3498DB)
soul_label    = label.Label(terminalio.FONT, text="Soul: [-----]",           x=10, y=170, color=0x9B59B6)
message_label = label.Label(terminalio.FONT, text="",                        x=10, y=188, color=0xFFFFFF)
status_label  = label.Label(terminalio.FONT, text="",                        x=10, y=203, color=0x888888)

for lbl in (bird_label, energy_label, body_label,
            mind_label, soul_label, message_label, status_label):
    main_group.append(lbl)

# ---------------------------
# PET LOGIC
# ---------------------------
def get_pet_face(energy):
    if energy > 70:
        return "( ^_^ )"
    elif energy > 30:
        return "( 0_0 )"
    else:
        return "( ._. )"

def draw_bar(value):
    filled = int(value / 10)
    return "[" + ("#" * filled) + ("-" * (10 - filled)) + "]"

def update_ui(energy):
    energy_label.text = f"Energy: {energy} {draw_bar(energy)}"

# ---------------------------
# DOTSTAR HELPERS
# ---------------------------
NUM_DOTSTARS = 5

def set_dotstars_color(color_tuple):
    for i in range(NUM_DOTSTARS):
        funhouse.peripherals.dotstars[i] = color_tuple
    funhouse.peripherals.dotstars.show()

# ---------------------------
# HIDE / SHOW DATA LABELS
# ---------------------------
def hide_labels():
    energy_label.text  = ""
    body_label.text    = ""
    mind_label.text    = ""
    soul_label.text    = ""
    message_label.text = ""
    status_label.text  = ""

def show_labels():
    energy_label.text = f"Energy: {last_energy} {draw_bar(last_energy)}"
    body_label.text   = f"Body: {draw_mbs_bar(body_val)}"
    mind_label.text   = f"Mind: {draw_mbs_bar(mind_val)}"
    soul_label.text   = f"Soul: {draw_mbs_bar(soul_val)}"

# ---------------------------
# SEND TO ADAFRUIT IO
# with bird animation during send
# ---------------------------
def send_to_io(energy, temp, humidity,
               mind=None, body=None, soul=None):

    feeds = [
        (temp_feed,     round(temp, 2)),
        (energy_feed,   energy),
        (humidity_feed, round(humidity, 2)),
    ]
    if mind is not None and mind > 0:
        feeds.append((mind_feed,  mind))
    if body is not None and body > 0:
        feeds.append((body_feed,  body))
    if soul is not None and soul > 0:
        feeds.append((soul_feed,  soul))

    # Move bird to center, hide data labels during send
    hide_labels()
    bird_label.y   = 40
    bird_label.color = 0x069494

    success     = True
    frame_index = 0

    for feed, value in feeds:
        # Animate bird frame before each send
        bird_label.text = BIRD_DANCE[frame_index % len(BIRD_DANCE)]
        frame_index    += 1

        try:
            print(f"Sending {value} to {feed['key']}...")
            io.send_data(feed["key"], value)
            print("Sent!")
        except Exception as e:
            print(f"Failed {feed['key']}:", e)
            success = False

        time.sleep(0.3)

    # Extra dance frames to fill time after last send
    for _ in range(2):
        bird_label.text = BIRD_DANCE[frame_index % len(BIRD_DANCE)]
        frame_index    += 1
        time.sleep(0.4)

    # Restore bird and labels
    bird_label.text  = BIRD_FRONT
    bird_label.y     = 10
    show_labels()

    return success

# ---------------------------
# LOGGING FEEDBACK
# ---------------------------
def show_log_feedback(success):
    global state
    state = STATE_LOGGING

    if success:
        message_label.text = "Saved!"
        bird_label.color   = 0x00FF00
        set_dotstars_color((0, 50, 0))
    else:
        message_label.text = "Some failed"
        bird_label.color   = 0xFF6600
        set_dotstars_color((50, 25, 0))

    time.sleep(1.5)
    bird_label.color   = 0x069494
    message_label.text = ""
    set_dotstars_color((0, 0, 0))
    state = STATE_ACTIVE

# ---------------------------
# SLIDER
# ---------------------------
last_energy = 0

def get_energy_from_slider():
    global last_energy
    raw = funhouse.peripherals.slider
    if raw is None:
        return last_energy
    value       = int(raw * 100)
    smoothed    = int(last_energy * 0.7 + value * 0.3)
    last_energy = smoothed
    return smoothed

# ---------------------------
# WAKE FROM SLEEP
# ---------------------------
def wake_from_sleep():
    global state, sleep_bob_dir
    state            = STATE_ACTIVE
    sleep_bob_dir    = 1
    bird_label.y     = 10
    bird_label.color = 0x069494
    bird_label.text  = BIRD_FRONT
    show_labels()
    set_dotstars_color((0, 0, 0))

# ---------------------------
# BUTTON & TOUCH STATE
# ---------------------------
last_button_sel  = False
last_button_down = False

TOUCH_MAP = [
    ("body", (50, 20, 20)),
    ("mind", (0,  20, 50)),
    ("soul", (30,  0, 50)),
]

# ---------------------------
# MAIN LOOP
# ---------------------------
while True:
    now    = time.monotonic()
    energy = get_energy_from_slider()

    current_sel  = funhouse.peripherals.button_sel
    current_down = funhouse.peripherals.button_down

    # --- TOUCH PADS ---
    touches = [
        funhouse.peripherals.captouch6,   # left  = Body
        funhouse.peripherals.captouch7,   # mid   = Mind
        funhouse.peripherals.captouch8,   # right = Soul
    ]

    for i, touched in enumerate(touches):
        if (touched and not last_touch[i]
                and (now - last_touch_time[i]) > TOUCH_DEBOUNCE):
            last_touch_time[i]    = now
            last_interaction_time = now
            name, dot_color       = TOUCH_MAP[i]

            if state == STATE_SLEEP:
                wake_from_sleep()

            if name == "body":
                body_val           = cycle_value(body_val)
                body_label.text    = f"Body: {draw_mbs_bar(body_val)}"
                message_label.text = f"Body: {body_val}/5"
            elif name == "mind":
                mind_val           = cycle_value(mind_val)
                mind_label.text    = f"Mind: {draw_mbs_bar(mind_val)}"
                message_label.text = f"Mind: {mind_val}/5"
            elif name == "soul":
                soul_val           = cycle_value(soul_val)
                soul_label.text    = f"Soul: {draw_mbs_bar(soul_val)}"
                message_label.text = f"Soul: {soul_val}/5"

            set_dotstars_color(dot_color)
            time.sleep(0.15)
            set_dotstars_color((0, 0, 0))

        last_touch[i] = touched

    # --- SEL button: log data ---
    if current_sel and not last_button_sel:
        last_interaction_time = now

        if state == STATE_SLEEP:
            wake_from_sleep()

        else:
            time_since_last = now - last_submit_time

            if time_since_last < SUBMIT_COOLDOWN:
                remaining          = int(SUBMIT_COOLDOWN - time_since_last)
                print(f"Cooldown active: {remaining}s remaining")
                message_label.text = f"Cooldown: {remaining}s"
                bird_label.color   = 0xFFAA00
                set_dotstars_color((50, 25, 0))
                time.sleep(1)
                set_dotstars_color((0, 0, 0))
                bird_label.color   = 0x069494
                message_label.text = ""

            else:
                temp     = funhouse.peripherals.temperature
                humidity = funhouse.peripherals.relative_humidity

                print(f"Energy:{energy} Temp:{temp} Hum:{humidity}")
                print(f"Mind:{mind_val} Body:{body_val} Soul:{soul_val}")

                status_label.text = "Sending..."
                success = send_to_io(
                    energy, temp, humidity,
                    mind=mind_val, body=body_val, soul=soul_val)

                last_submit_time  = now
                status_label.text = ""
                show_log_feedback(success)

                mind_val           = 0
                body_val           = 0
                soul_val           = 0
                body_label.text    = "Body: [-----]"
                mind_label.text    = "Mind: [-----]"
                soul_label.text    = "Soul: [-----]"
                message_label.text = ""

    # --- DOWN button: placeholder ---
    if current_down and not last_button_down:
        last_interaction_time = now

        if state == STATE_SLEEP:
            wake_from_sleep()
        else:
            message_label.text = "Mode soon"
            time.sleep(0.5)
            message_label.text = ""

    last_button_sel  = current_sel
    last_button_down = current_down

    # --- STATE: ACTIVE ---
    if state == STATE_ACTIVE:
        update_ui(energy)
        bird_label.text = BIRD_FRONT
        if now - last_interaction_time > SLEEP_TIMEOUT:
            state = STATE_SLEEP

    # --- STATE: SLEEP — slow bob ---
    elif state == STATE_SLEEP:
        hide_labels()
        bird_label.color = 0x034A4A

        if now - last_sleep_time > SLEEP_DELAY:
            bird_label.text  = BIRD_SLEEP
            bird_label.y    += sleep_bob_dir
            last_sleep_time  = now
            if bird_label.y >= 14:
                sleep_bob_dir = -1
            elif bird_label.y <= 8:
                sleep_bob_dir = 1

        set_dotstars_color((0, 0, 5))

    time.sleep(0.05)
