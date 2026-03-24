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

# ---------------------------
# GET CREDENTIALS FROM ENV
# ---------------------------
ssid = os.getenv("CIRCUITPY_WIFI_SSID")
password = os.getenv("CIRCUITPY_WIFI_PASSWORD")
aio_username = os.getenv("ADAFRUIT_AIO_USERNAME")
aio_key = os.getenv("ADAFRUIT_AIO_KEY")
timezone = os.getenv("TIMEZONE")

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
STATE_ACTIVE = "ACTIVE"
STATE_LOGGING = "LOGGING"
STATE_SLEEP = "SLEEP"

state = STATE_ACTIVE
last_interaction_time = time.monotonic()
SLEEP_TIMEOUT = 60  # seconds

# ---------------------------
# UI GROUPS
# ---------------------------
main_group = displayio.Group()
display.root_group = main_group

pet_label = label.Label(terminalio.FONT, text="( -_- )", scale=2, x=60, y=60)
energy_label = label.Label(terminalio.FONT, text="Energy: 0", x=10, y=120)
bar_label = label.Label(terminalio.FONT, text="[----------]", x=10, y=140)
message_label = label.Label(terminalio.FONT, text="", x=40, y=100)

main_group.append(pet_label)
main_group.append(energy_label)
main_group.append(bar_label)
main_group.append(message_label)

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
    pet_label.text = get_pet_face(energy)
    energy_label.text = f"Energy: {energy}"
    bar_label.text = draw_bar(energy)

# ---------------------------
# DOTSTAR HELPERS
# ---------------------------
NUM_DOTSTARS = 5
def set_dotstars_color(color_tuple):
    for i in range(NUM_DOTSTARS):
        funhouse.peripherals.dotstars[i] = color_tuple
    funhouse.peripherals.dotstars.show()

# ---------------------------
# LOGGING FEEDBACK
# ---------------------------
def show_log_feedback(energy):
    global state
    state = STATE_LOGGING
    message_label.text = "Saved! 💾"
    pet_label.text = "( ^o^ )"
    set_dotstars_color((0, 50, 0))
    time.sleep(1)
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
last_button_a = False  # SEL
last_button_b = False  # DOWN

# ---------------------------
# SEND DATA TO ADAFRUIT IO FEEDS
# ---------------------------
def send_to_aio(feed, value):
    if not aio_username or not aio_key:
        print(f"Skipping {feed} send: missing credentials")
        return
    url = f"https://io.adafruit.com/api/v2/{aio_username}/feeds/{feed}/data"
    headers = {"X-AIO-Key": aio_key, "Content-Type": "application/json"}
    data = {"value": value}
    print(f"Attempting to send {value} to feed '{feed}'...")
    try:
        response = requests.post(url, json=data, headers=headers)
        print(f"Success! {feed} status code:", response.status_code)
    except Exception as e:
        print(f"Failed to post {feed}: {e}")

# ---------------------------
# MAIN LOOP
# ---------------------------
while True:
    now = time.monotonic()
    energy = get_energy_from_slider()

    # -----------------------
    # BUTTON INPUT
    # -----------------------
    current_a = funhouse.peripherals.button_sel
    current_b = funhouse.peripherals.button_down

    if current_a and not last_button_a:
        last_interaction_time = now
        show_log_feedback(energy)

        # -----------------------
        # SENSOR DATA
        # -----------------------
        temp = funhouse.peripherals.temperature
        humidity = funhouse.peripherals.relative_humidity
        motion = int(funhouse.peripherals.pir_sensor)

        # -----------------------
        # LOG TO ADAFRUIT IO
        # -----------------------
        send_to_aio("energy", energy)
        send_to_aio("button_sel", 1)
        send_to_aio("temperature", temp)
        send_to_aio("humidity", humidity)
        send_to_aio("motion", motion)

    if current_b and not last_button_b:
        last_interaction_time = now
        message_label.text = "Mode soon™"
        time.sleep(0.5)
        message_label.text = ""

    last_button_a = current_a
    last_button_b = current_b

    # -----------------------
    # STATE: ACTIVE
    # -----------------------
    if state == STATE_ACTIVE:
        update_ui(energy)
        if now - last_interaction_time > SLEEP_TIMEOUT:
            state = STATE_SLEEP

    # -----------------------
    # STATE: SLEEP
    # -----------------------
    elif state == STATE_SLEEP:
        pet_label.text = "( -.- ) zZ"
        energy_label.text = ""
        bar_label.text = ""

        # soft LED pulse
        set_dotstars_color((0, 0, 10))

        # wake conditions
        slider_val = funhouse.peripherals.slider or 0
        if funhouse.peripherals.button_sel or funhouse.peripherals.button_down or slider_val > 0.05:
            state = STATE_ACTIVE
            last_interaction_time = now
            set_dotstars_color((0, 0, 0))

    time.sleep(0.1)
