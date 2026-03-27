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
ssid          = os.getenv("CIRCUITPY_WIFI_SSID")
password      = os.getenv("CIRCUITPY_WIFI_PASSWORD")
apps_script_url = os.getenv("APPS_SCRIPT_URL")   # your deployed Web App URL
logger_key    = os.getenv("LOGGER_SECRET_KEY")    # must match SECRET_KEY in Apps Script

# ---------------------------
# CONNECT WIFI
# ---------------------------
print("Connecting to WiFi", ssid)
wifi.radio.connect(ssid, password)
print("Connected! IP:", wifi.radio.ipv4_address)

pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

# ---------------------------
# INIT FUNHOUSE
# ---------------------------
funhouse = FunHouse(default_bg=0x000000)
display = board.DISPLAY

# ---------------------------
# STATE MACHINE
# ---------------------------
STATE_ACTIVE  = "ACTIVE"
STATE_LOGGING = "LOGGING"
STATE_SLEEP   = "SLEEP"

state = STATE_ACTIVE
last_interaction_time = time.monotonic()
SLEEP_TIMEOUT = 60

# ---------------------------
# UI GROUPS
# ---------------------------
main_group = displayio.Group()
display.root_group = main_group

pet_label     = label.Label(terminalio.FONT, text="( -_- )", scale=2, x=60, y=60)
energy_label  = label.Label(terminalio.FONT, text="Energy: 0", x=10, y=120)
bar_label     = label.Label(terminalio.FONT, text="[----------]", x=10, y=140)
message_label = label.Label(terminalio.FONT, text="", x=40, y=100)
status_label  = label.Label(terminalio.FONT, text="", x=10, y=160)   # NEW: shows upload result

main_group.append(pet_label)
main_group.append(energy_label)
main_group.append(bar_label)
main_group.append(message_label)
main_group.append(status_label)

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

# ---------------------------
# DOTSTAR HELPERS
# ---------------------------
NUM_DOTSTARS = 5
def set_dotstars_color(color_tuple):
    for i in range(NUM_DOTSTARS):
        funhouse.peripherals.dotstars[i] = color_tuple
    funhouse.peripherals.dotstars.show()

# ---------------------------
# GET EPOCH TIME
# ---------------------------
def get_epoch_time():
    try:
        r = requests.get("https://io.adafruit.com/api/v2/time/seconds")
        raw = r.text.strip()
        r.close()
        time.sleep(0.5)  # give the socket time to actually close
        if raw.isdigit():
            return int(raw)
        else:
            print("Bad time response:", raw[:50])
            return int(time.monotonic())
    except Exception as e:
        print("Time fetch failed:", e)
        return int(time.monotonic())

# ---------------------------
# SEND TO APPS SCRIPT
# ---------------------------
def send_to_sheet(energy, temp, humidity, motion):
    if not apps_script_url or not logger_key:
        print("Missing APPS_SCRIPT_URL or LOGGER_SECRET_KEY in settings.toml")
        status_label.text = "Config error"
        return False

    timestamp = int(time.monotonic())

    payload = json.dumps({
        "key":         logger_key,
        "timestamp":   timestamp,
        "energy":      energy,
        "temperature": round(temp, 2),
        "humidity":    round(humidity, 2),
        "motion":      motion,
    })

    headers = {"Content-Type": "application/json"}

    print("Posting to Apps Script...")
    print("Payload:", payload)

    # Fresh session every time — kills any lingering socket from last attempt
    fresh_pool = socketpool.SocketPool(wifi.radio)
    fresh_requests = adafruit_requests.Session(fresh_pool, ssl.create_default_context())

    response = None
    try:
        response = fresh_requests.post(apps_script_url, data=payload, headers=headers)
        raw = response.text
        print("Raw response:", raw[:100])
        status_label.text = "Logged OK"
        return True

    except Exception as e:
        print("Send failed:", e)
        status_label.text = "Send failed"
        return False

    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        # Explicitly dereference the session so CircuitPython GC cleans it up
        fresh_requests = None
        fresh_pool = None
        time.sleep(1)

# ---------------------------
# LOGGING FEEDBACK
# ---------------------------
def show_log_feedback(success):
    global state
    state = STATE_LOGGING

    if success:
        message_label.text = "Saved!"
        pet_label.text = "( ^o^ )"
        set_dotstars_color((0, 50, 0))
    else:
        message_label.text = "Failed!"
        pet_label.text = "( >_< )"
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
    value = int(raw * 100)
    smoothed = int(last_energy * 0.7 + value * 0.3)
    last_energy = smoothed
    return smoothed

# ---------------------------
# BUTTON STATE
# ---------------------------
last_button_a = False
last_button_b = False

# ---------------------------
# MAIN LOOP
# ---------------------------
while True:
    now    = time.monotonic()
    energy = get_energy_from_slider()

    current_a = funhouse.peripherals.button_sel
    current_b = funhouse.peripherals.button_down

    # SEL button — log data
    if current_a and not last_button_a:
        last_interaction_time = now

        temp     = funhouse.peripherals.temperature
        humidity = funhouse.peripherals.relative_humidity
        motion   = int(funhouse.peripherals.pir_sensor)

        print(f"Energy:{energy} Temp:{temp} Hum:{humidity} Motion:{motion}")

        success = send_to_sheet(energy, temp, humidity, motion)
        show_log_feedback(success)

    # DOWN button — placeholder
    if current_b and not last_button_b:
        last_interaction_time = now
        message_label.text = "Mode soon"
        time.sleep(0.5)
        message_label.text = ""

    last_button_a = current_a
    last_button_b = current_b

    # STATE: ACTIVE
    if state == STATE_ACTIVE:
        update_ui(energy)
        if now - last_interaction_time > SLEEP_TIMEOUT:
            state = STATE_SLEEP

    # STATE: SLEEP
    elif state == STATE_SLEEP:
        pet_label.text    = "( -.- ) zZ"
        energy_label.text = ""
        bar_label.text    = ""
        set_dotstars_color((0, 0, 10))

        slider_val = funhouse.peripherals.slider or 0
        if funhouse.peripherals.button_sel or funhouse.peripherals.button_down or slider_val > 0.05:
            state = STATE_ACTIVE
            last_interaction_time = now
            set_dotstars_color((0, 0, 0))

    time.sleep(0.1)
