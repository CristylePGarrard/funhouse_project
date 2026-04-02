import time
import board
import displayio
import terminalio
from adafruit_display_text import label
from adafruit_funhouse import FunHouse
import os
import ssl
import wifi
import socketpool
import adafruit_requests
import json

# ---------------------------
# GET CREDENTIALS FROM ENV
# ---------------------------
ssid            = os.getenv("CIRCUITPY_WIFI_SSID")
password        = os.getenv("CIRCUITPY_WIFI_PASSWORD")
apps_script_url = os.getenv("APPS_SCRIPT_URL")
logger_key      = os.getenv("LOGGER_SECRET_KEY")

# ---------------------------
# CONNECT WIFI
# ---------------------------
print("Connecting to WiFi", ssid)
wifi.radio.connect(ssid, password)
print("Connected! IP:", wifi.radio.ipv4_address)

# ---------------------------
# SESSION MANAGEMENT
# One pool, one session, one SSL context — never recreated
# ---------------------------
_pool    = socketpool.SocketPool(wifi.radio)
_ssl_ctx = ssl.create_default_context()
_session = adafruit_requests.Session(_pool, _ssl_ctx)

def send_to_sheet(energy, temp, humidity, motion,
                  mind=None, body=None, soul=None):

    if not apps_script_url or not logger_key:
        status_label.text = "Config error"
        return False

    timestamp = int(time.monotonic())

    payload_dict = {
        "key":         logger_key,
        "timestamp":   timestamp,
        "energy":      energy,
        "temperature": round(temp, 2),
        "humidity":    round(humidity, 2),
        "motion":      motion,
    }

    if mind is not None and mind > 0:
        payload_dict["mind"] = mind
    if body is not None and body > 0:
        payload_dict["body"] = body
    if soul is not None and soul > 0:
        payload_dict["soul"] = soul

    payload = json.dumps(payload_dict)
    headers = {"Content-Type": "application/json"}

    print("Posting to Apps Script...")
    print("Payload:", payload)

    response = None
    try:
        response = _session.post(
            apps_script_url, data=payload, headers=headers)

        # Close immediately — don't read body, don't follow redirect
        try:
            response.close()
        except Exception:
            pass

        print("POST sent.")
        status_label.text = "Logged OK"
        return True

    except Exception as e:
        print("Send failed:", e)
        status_label.text = "Send failed"

        # Only reconnect wifi if we actually lost the connection
        if "wifi" in str(e).lower() or "network" in str(e).lower():
            print("WiFi issue, reconnecting...")
            try:
                wifi.radio.connect(ssid, password)
                print("Reconnected:", wifi.radio.ipv4_address)
            except Exception as e2:
                print("Reconnect failed:", e2)

        return False

    finally:
        # Small delay to let the TCP connection close gracefully
        # before the next request — no radio reset needed
        time.sleep(2)
# ---------------------------
# INIT FUNHOUSE
# ---------------------------
funhouse = FunHouse(default_bg=0x000000)
display  = board.DISPLAY

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
# TOUCH PAD CONFIG
# Left=Body, Mid=Mind, Right=Soul
# ---------------------------
MAX_VAL        = 5
last_touch      = [False, False, False]
last_touch_time = [0.0, 0.0, 0.0]
TOUCH_DEBOUNCE  = 0.3

def cycle_value(current):
    return (current + 1) % (MAX_VAL + 1)

def draw_blocks(value, max_val=5):
    return ("\u2588" * value) + ("\u2591" * (max_val - value))

# ---------------------------
# MIND / BODY / SOUL VALUES
# ---------------------------
mind_val = 0
body_val = 0
soul_val = 0

# ---------------------------
# SUBMISSION COOLDOWN
# ---------------------------
SUBMIT_COOLDOWN  = 100
last_submit_time = -SUBMIT_COOLDOWN

# ---------------------------
# UI GROUPS
# ---------------------------
main_group = displayio.Group()
display.root_group = main_group

pet_label     = label.Label(terminalio.FONT, text="( -_- )", scale=2, x=40,  y=25,  color=0xFFFFFF)
energy_label  = label.Label(terminalio.FONT, text="Energy: 0",        x=10,  y=65,  color=0xFFFF00)
bar_label     = label.Label(terminalio.FONT, text="[----------]",      x=10,  y=80,  color=0xFFFF00)
body_label    = label.Label(terminalio.FONT, text="Bod:\u2591\u2591\u2591\u2591\u2591", x=10, y=100, color=0x44FF44)
mind_label    = label.Label(terminalio.FONT, text="Mnd:\u2591\u2591\u2591\u2591\u2591", x=10, y=115, color=0x4444FF)
soul_label    = label.Label(terminalio.FONT, text="Sol:\u2591\u2591\u2591\u2591\u2591", x=10, y=130, color=0xCC44FF)
message_label = label.Label(terminalio.FONT, text="",                  x=10,  y=150, color=0xFFFFFF)
status_label  = label.Label(terminalio.FONT, text="",                  x=10,  y=165, color=0x888888)

for lbl in (pet_label, energy_label, bar_label,
            body_label, mind_label, soul_label,
            message_label, status_label):
    main_group.append(lbl)

# ---------------------------
# PET LOGIC
# ---------------------------
def get_pet_face(energy):
    if energy > 70:
        return "( ^_^ )"
    elif energy > 30:
        return "( -_- )"
    else:
        return "( -.- )"

def draw_bar(value):
    blocks = int(value / 10)
    return "[" + ("#" * blocks) + ("-" * (10 - blocks)) + "]"

def update_ui(energy):
    pet_label.text    = get_pet_face(energy)
    energy_label.text = f"Energy: {energy}"
    bar_label.text    = draw_bar(energy)
    body_label.text   = f"Bod:{draw_blocks(body_val)}"
    mind_label.text   = f"Mnd:{draw_blocks(mind_val)}"
    soul_label.text   = f"Sol:{draw_blocks(soul_val)}"

# ---------------------------
# DOTSTAR HELPERS
# ---------------------------
NUM_DOTSTARS = 5

def set_dotstars_color(color_tuple):
    for i in range(NUM_DOTSTARS):
        funhouse.peripherals.dotstars[i] = color_tuple
    funhouse.peripherals.dotstars.show()

# ---------------------------
# SEND TO APPS SCRIPT
# ---------------------------
def send_to_sheet(energy, temp, humidity, motion,
                  mind=None, body=None, soul=None):

    if not apps_script_url or not logger_key:
        status_label.text = "Config error"
        return False

    timestamp = int(time.monotonic())

    payload_dict = {
        "key":         logger_key,
        "timestamp":   timestamp,
        "energy":      energy,
        "temperature": round(temp, 2),
        "humidity":    round(humidity, 2),
        "motion":      motion,
    }

    if mind is not None and mind > 0:
        payload_dict["mind"] = mind
    if body is not None and body > 0:
        payload_dict["body"] = body
    if soul is not None and soul > 0:
        payload_dict["soul"] = soul

    payload = json.dumps(payload_dict)
    headers = {"Content-Type": "application/json"}

    print("Posting to Apps Script...")
    print("Payload:", payload)

    response = None
    try:
        p = socketpool.SocketPool(wifi.radio)
        r = adafruit_requests.Session(p, ssl.create_default_context())
        response = r.post(apps_script_url, data=payload, headers=headers)
        try:
            response.close()
        except Exception:
            pass
        response = None
        print("POST sent.")
        return True

    except Exception as e:
        print("Send failed:", e)
        return False

    finally:
        try:
            wifi.radio.stop_station()
        except Exception:
            pass
        time.sleep(2)
        try:
            wifi.radio.connect(ssid, password)
            print("Radio reset complete:", wifi.radio.ipv4_address)
        except Exception as e:
            print("Reconnect failed:", e)
        time.sleep(0.5)

# ---------------------------
# LOGGING FEEDBACK
# ---------------------------
def show_log_feedback(success):
    global state
    state = STATE_LOGGING

    if success:
        message_label.text = "Saved!"
        pet_label.text     = "( ^o^ )"
        set_dotstars_color((0, 50, 0))
    else:
        message_label.text = "Failed!"
        pet_label.text     = "( >_< )"
        set_dotstars_color((50, 0, 0))

    time.sleep(1.5)
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
# BUTTON STATE
# ---------------------------
last_button_sel  = False
last_button_down = False

TOUCH_MAP = [
    ("body", (0, 50, 0)),   # green
    ("mind", (0, 0, 50)),   # blue
    ("soul", (30, 0, 50)),  # purple
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
        funhouse.peripherals.captouch6,
        funhouse.peripherals.captouch7,
        funhouse.peripherals.captouch8,
    ]

    for i, touched in enumerate(touches):
        if touched and not last_touch[i] and (now - last_touch_time[i]) > TOUCH_DEBOUNCE:
            last_touch_time[i]    = now
            last_interaction_time = now
            name, dot_color       = TOUCH_MAP[i]

            if name == "body":
                body_val = cycle_value(body_val)
                body_label.text    = f"Bod:{draw_blocks(body_val)}"
                message_label.text = f"Body: {body_val}/5"
            elif name == "mind":
                mind_val = cycle_value(mind_val)
                mind_label.text    = f"Mnd:{draw_blocks(mind_val)}"
                message_label.text = f"Mind: {mind_val}/5"
            elif name == "soul":
                soul_val = cycle_value(soul_val)
                soul_label.text    = f"Sol:{draw_blocks(soul_val)}"
                message_label.text = f"Soul: {soul_val}/5"

            set_dotstars_color(dot_color)
            time.sleep(0.15)
            set_dotstars_color((0, 0, 0))

        last_touch[i] = touched

    # --- SEL button: log data ---
    if current_sel and not last_button_sel:
        last_interaction_time = now
        time_since_last       = now - last_submit_time

        if time_since_last < SUBMIT_COOLDOWN:
            remaining          = int(SUBMIT_COOLDOWN - time_since_last)
            print(f"Cooldown active: {remaining}s remaining")
            message_label.text = f"Cooldown: {remaining}s"
            pet_label.text     = "( ._. )"
            set_dotstars_color((50, 25, 0))
            time.sleep(1)
            set_dotstars_color((0, 0, 0))
            message_label.text = ""

        else:
            temp     = funhouse.peripherals.temperature
            humidity = funhouse.peripherals.relative_humidity
            motion   = int(funhouse.peripherals.pir_sensor)

            print(f"Energy:{energy} Temp:{temp} Hum:{humidity} Motion:{motion}")
            print(f"Mind:{mind_val} Body:{body_val} Soul:{soul_val}")

            success = send_to_sheet(
                energy, temp, humidity, motion,
                mind=mind_val, body=body_val, soul=soul_val)

            last_submit_time   = now
            show_log_feedback(success)

            mind_val = 0
            body_val = 0
            soul_val = 0
            message_label.text = ""


    # --- DOWN button: placeholder ---
    if current_down and not last_button_down:
        last_interaction_time = now
        message_label.text    = "Mode soon"
        time.sleep(0.5)
        message_label.text    = ""

    last_button_sel  = current_sel
    last_button_down = current_down

    # --- STATE: ACTIVE ---
    if state == STATE_ACTIVE:
        update_ui(energy)
        if now - last_interaction_time > SLEEP_TIMEOUT:
            state = STATE_SLEEP

    # --- STATE: SLEEP ---
    elif state == STATE_SLEEP:
        pet_label.text    = "( -.- ) zZ"
        energy_label.text = ""
        bar_label.text    = ""
        body_label.text   = ""
        mind_label.text   = ""
        soul_label.text   = ""
        set_dotstars_color((0, 0, 10))

        slider_val = funhouse.peripherals.slider or 0
        if (funhouse.peripherals.button_sel or
                funhouse.peripherals.button_down or
                slider_val > 0.05):
            state                 = STATE_ACTIVE
            last_interaction_time = now
            set_dotstars_color((0, 0, 0))

    time.sleep(0.1)
