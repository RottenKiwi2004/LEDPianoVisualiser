import threading
import time
from rpi_ws281x import *
import mido
from flask import Flask, request, render_template, Response, jsonify
import os
from random import randint
from datetime import datetime
import csv
import logging

# ----------------------------------------------- CONSTANT ----------------------------------------------- #
LED_COUNT       = 144     
LED_PIN         = 18      
LED_FREQ_HZ     = 800000  
LED_DMA         = 10      
LED_BRIGHTNESS  = 100     
LED_INVERT      = False   
LED_CHANNEL     = 0       
INPUT_USB_PORT  = 1
OUTPUT_USB_PORT = 1
DECAY_RATE      = 0.01 # Still unused: use to fade out the pressed key
# ----------------------------------------- ADJUSTABLE PARAMETER ----------------------------------------- #
brightness      = 100
profile         = 0
lightPreset     = 0
hue             = 0
saturation      = 100
lightness       = 50
enablePlayback  = False
baseColor       = (5, 5, 5)
guideColor      = (255, 255, 0)
correctColor    = (0, 255, 0)
falseColor      = (255, 0, 0)
hueShift        = 3
hueCycling      = False
midiFile        = "littleStar.mid"
currentMode     = 0 # 0 = Free play # 1 = With song
# ------------------------------------------ DATA TO BE FETCHED ------------------------------------------ #
percentage      = 0
accuracy        = 100
tempTable       = None
tempFileList    = None
#--------------------------------------------- UTIL FUNCTION --------------------------------------------- #
def getColor(rgbTuple):
    return Color(int(rgbTuple[0]), int(rgbTuple[1]), int(rgbTuple[2]))

def hslToRgb(h, s, l):
        h %= 360
        s /=100
        l /= 100
        c = (1 - abs(2 * l - 1)) * s
        x = c * (1 - abs((h / 60) % 2 - 1))
        m = l - c / 2
        rArr = [c, x, 0, 0, x, c]
        gArr = [x, c, c, x, 0, 0]
        bArr = [0, 0, x, c, c, x]
        rp, gp, bp = rArr[h // 60], gArr[h // 60], bArr[h // 60]
        r = (rp + m) * 255
        g = (gp + m) * 255
        b = (bp + m) * 255
        return r, g, b

noteLookup = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
def decodeNote(note):
    return noteLookup[note % 12] + str(note // 12 - 1)

def parseHexToInt(hexChar):
    if 48 <= ord(hexChar) <= 57:
        return ord(hexChar) - 48
    return ord(hexChar) - 87

def updateCSV(filePath):
    if not os.path.exists(filePath):
        with open(filePath, 'w') as f:
            f.write('Timestamp,Accuracy\n')
        time.sleep(0.2)
    with open(filePath) as csvFile:
        csvReader = csv.reader(csvFile)
        allRows = []
        for row in csvReader:
            allRows.append(row)
        global tempTable
        if len(allRows) > 6:
            tempTable = allRows[-5:]
        else:
            tempTable = allRows[1:]
        tempTable = tempTable[::-1]

def updateSong():
    midiDirectory = os.listdir("./midis")
    allFiles = []
    for fileName in midiDirectory:
        allFiles.append(fileName[:-4])
    global tempFileList
    tempFileList = allFiles
# -------------------------------------------- INITIALISATION -------------------------------------------- #
strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
strip.begin()
for i in range(LED_COUNT):
    strip.setPixelColor(i, getColor(baseColor))
strip.show()
print("Available MIDI:")
print(f"Input Port {INPUT_USB_PORT}: {mido.get_input_names()[INPUT_USB_PORT]}")
for port, name in enumerate(mido.get_input_names()):
        print(f"{port}: {name}")
inPort  = mido.open_input(mido.get_input_names()[INPUT_USB_PORT])
for port, name in enumerate(mido.get_output_names()):
        print(f"{port}: {name}")
outPort = mido.open_output(mido.get_output_names()[OUTPUT_USB_PORT])

# -------------------------------------------- GLOBAL CLASSES -------------------------------------------- #

class MidiPlay:
    def __init__(self):
        # Index = midiCode
        self.arr = [False for _ in range(120)]
        self.check = [False for _ in range(120)]
        self.correct = 0
        self.mistake = 0

    def press(self, midiCode):
        self.arr[midiCode] = True
        note = (midiCode - 24) * 2
        if self.check[midiCode]:
            strip.setPixelColor(note, getColor(correctColor))
            strip.setPixelColor(note+1, getColor(correctColor))
            self.correct += 1
        else:
            strip.setPixelColor(note, getColor(falseColor))
            strip.setPixelColor(note+1, getColor(falseColor))
            self.mistake += 1
        strip.show()
        # self.debug()

    def release(self, midiCode):
        self.arr[midiCode] = False
        note = (midiCode - 24) * 2
        if self.check[midiCode]:
            strip.setPixelColor(note, getColor(guideColor))
            strip.setPixelColor(note+1, getColor(guideColor))
        else:
            strip.setPixelColor(note, getColor(baseColor))
            strip.setPixelColor(note+1, getColor(baseColor))
        strip.show()
        # self.debug()

    def waitFor(self, pressArr, releaseArr):
        for midiCode in pressArr:
            note = (midiCode - 24) * 2
            self.check[midiCode] = True
            strip.setPixelColor(note, getColor(guideColor))
            strip.setPixelColor(note+1, getColor(guideColor))
            
        for midiCode in releaseArr:
            note = (midiCode - 24) * 2
            self.check[midiCode] = False
            strip.setPixelColor(note, getColor(baseColor))
            strip.setPixelColor(note+1, getColor(baseColor))
        strip.show()
    
    def checkNote(self):
        for i in range(120):
            if self.check[i] != self.arr[i]:
                return False
        return True

    def getStats(self):
        return self.correct, self.mistake

    def debug(self):
        print("Play ", self.arr)
        print("Check", self.check)

class LightHandler:
    def __init__(self):
        self.hue = 0
        self.mode = 0 # Default

    def setMode(self ,mode):
        self.mode = mode

    def keyPressed(self):
        global currentMode
        if currentMode != 0:
            return
        global hueCycling
        global hueShift
        global hue
        self.hue = hue
        if hueCycling and self.mode == 0:
            self.hue += hueShift
            self.hue %= 360

        hue = self.hue

    def getColor(self):
        # Default
        if self.mode == 0:
            global saturation
            global lightness
            return getColor(hslToRgb(self.hue, saturation, lightness))
        # Christmas
        if self.mode == 1:
            colorList = [(255, 255, 255), (255, 0, 0), (0, 255, 0)]
            return getColor(colorList[randint(0, len(colorList) - 1)])
        # Halloween
        if self.mode == 2:
            colorList = [(255, 162, 0), (128, 0, 255)]
            return getColor(colorList[randint(0, len(colorList) - 1)])
        if self.mode == 3:
            colorList = [(113, 29, 176), (194, 18, 146), (239, 64, 64), (255, 167, 50)]
            return getColor(colorList[randint(0, len(colorList) - 1)])
        if self.mode == 4:
            colorList = [(54, 47, 217), (26, 172, 172), (46, 151, 167), (238, 238, 238)]
            return getColor(colorList[randint(0, len(colorList) - 1)])
        if self.mode == 5:
            colorList = [(134, 10, 53), (175, 38, 85), (0, 255, 8), (243, 243, 243)]
            return getColor(colorList[randint(0, len(colorList) - 1)])
        if self.mode == 6:
            colorList = [(55, 139, 174), (55, 139, 174), (55, 139, 174), (55, 139, 174), (55, 139, 174), (55, 139, 174), (55, 139, 174), (255, 77, 0)]
            return getColor(colorList[randint(0, len(colorList) - 1)])

player = MidiPlay()
light = LightHandler()
# ---------------------------------------------- MIDI INPUT ---------------------------------------------- #
def midiThread():
    global player
    global saturation
    global lightness
    global hue
    for msg in inPort:
        if msg.type == "note_on":
            if currentMode == 0:
                light.keyPressed()
                note = (msg.note - 24) * 2
                color = light.getColor()
                strip.setPixelColor(note,     color)
                strip.setPixelColor(note + 1, color)
                strip.show()
            if currentMode == 1:
                player.press(msg.note)
                global accuracy
                correct, mistake = player.getStats()
                accuracy = round(correct / (correct + mistake) * 100, 2)

        if msg.type == "note_off":
            if currentMode == 0:
                note = (msg.note - 24) * 2
                strip.setPixelColor(note,     getColor(baseColor))
                strip.setPixelColor(note + 1, getColor(baseColor))
                strip.show()

            if currentMode == 1:
                player.release(msg.note)

# ------------------------------------------- MIDI FILE PLAYER ------------------------------------------- #
def midiFilePlayer():
    global midiFile
    global outPort
    global enablePlayback
    global player
    global currentMode

    while True:
        if currentMode != 1:
            continue
        player = MidiPlay()
        progressFile = f"./progress/{profile}/{midiFile[:-4]}.csv"
    
        mid = mido.MidiFile(f'./midis/{midiFile}')
        allNotes = [msg.dict() for msg in mid]

        firstNoteIdx = 0
        for msg in allNotes:
            if msg["type"] == 'note_on':
                break
            firstNoteIdx += 1


        i = 0
        noteToPress = []
        noteToRelease = []
        while i < len(allNotes):

            # print(i, allNotes[i])

            # Next note needs delay
            if allNotes[i]["time"] != 0:
                waitTime = allNotes[i]["time"]
                player.waitFor(noteToPress, noteToRelease)
                print(noteToPress, noteToRelease)
                if enablePlayback:
                    for note in noteToPress:
                        outPort.send(mido.Message('note_on', channel=0, note=note, velocity=64))
                    for note in noteToRelease:
                        outPort.send(mido.Message('note_off', channel=0, note=note, velocity=0))
                    
                while not player.checkNote():
                    if currentMode == 1:
                        continue
                    else:
                        i = 0
                        allNotes = []
                        player = MidiPlay()
                        for i in range(LED_COUNT):
                            strip.setPixelColor(i, getColor(baseColor))
                        strip.show()
                        break

                if currentMode != 1:
                    i = 0
                    allNotes = []
                    player = MidiPlay()
                    for i in range(LED_COUNT):
                        strip.setPixelColor(i, getColor(baseColor))
                    strip.show()
                    break

                global percentage
                percentage = int((i - firstNoteIdx) / len(allNotes) * 100)
                noteToPress = []
                noteToRelease = []
                time.sleep(float(waitTime))


            midiType = allNotes[i]["type"]
            # END OF TRACK
            if midiType == 'end_of_track':
                # global percentage
                # percentage = 100
                for i in range(LED_COUNT):
                    strip.setPixelColor(i, getColor(correctColor))
                strip.show()
                time.sleep(0.5)
                for i in range(LED_COUNT):
                    strip.setPixelColor(i, getColor(baseColor))
                strip.show()
                currentMode = 0
                percentage = 0
                if not os.path.exists(progressFile):
                    with open(progressFile, 'w') as f:
                        f.write('Timestamp,Accuracy\n')
                    time.sleep(0.2)
                with open(progressFile, 'a') as f:
                    global accuracy
                    f.write(datetime.now().strftime('%H:%M %d/%m/%y')+f',{accuracy}%\n')
                updateCSV(progressFile)
                break
            # PASS OTHER SETUP PART
            if midiType != 'note_on' and midiType != 'note_off':
                i += 1
                continue
            # NOTE_OFF
            if allNotes[i]["velocity"] == 0 or midiType == 'note_off':
                noteToRelease.append(allNotes[i]["note"])
            # NOTE_ON
            else:
                noteToPress.append(allNotes[i]["note"])
            i += 1

# --------------------------------------------- FLASK SERVER --------------------------------------------- #
app = Flask(__name__)
UPLOAD_FOLDER = './midis'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/')
def index():
    updateSong()
    return render_template('index.html')

@app.route('/adjust', methods=['POST'])
def post_example():
    data = request.get_json()
    if not data:
        return
    property = data["property"]
    value = data["value"]

    global profile
    global midiFile
    if property == "brightness":
        global brightness
        brightness = int(value)
        strip.setBrightness(brightness)
        strip.show()
    if property == "hueCycling":
        global hueCycling
        hueCycling = value
    if property == "enablePlayback":
        global enablePlayback
        enablePlayback = value
    if property == "profile":
        profile = int(value)
        progressFile = f"./progress/{profile}/{midiFile[:-4]}.csv"
        updateCSV(progressFile)
    if property == "lightPreset":
        global lightPreset
        lightPreset = int(value)
        light.setMode(lightPreset)
    if property == "baseColor":
        global baseColor
        value = value[1:]
        r = parseHexToInt(value[0]) * 16 + parseHexToInt(value[1])
        g = parseHexToInt(value[2]) * 16 + parseHexToInt(value[3])
        b = parseHexToInt(value[4]) * 16 + parseHexToInt(value[5])
        value = (r, g, b)
        baseColor = value
        for i in range(LED_COUNT):
            strip.setPixelColor(i, getColor(baseColor))
        strip.show()
    if property == "guideColor":
        global guideColor
        value = value[1:]
        r = parseHexToInt(value[0]) * 16 + parseHexToInt(value[1])
        g = parseHexToInt(value[2]) * 16 + parseHexToInt(value[3])
        b = parseHexToInt(value[4]) * 16 + parseHexToInt(value[5])
        value = (r, g, b)
        guideColor = value
    if property == "correctColor":
        global correctColor
        value = value[1:]
        r = parseHexToInt(value[0]) * 16 + parseHexToInt(value[1])
        g = parseHexToInt(value[2]) * 16 + parseHexToInt(value[3])
        b = parseHexToInt(value[4]) * 16 + parseHexToInt(value[5])
        value = (r, g, b)
        correctColor = value
    if property == "falseColor":
        global falseColor
        value = value[1:]
        r = parseHexToInt(value[0]) * 16 + parseHexToInt(value[1])
        g = parseHexToInt(value[2]) * 16 + parseHexToInt(value[3])
        b = parseHexToInt(value[4]) * 16 + parseHexToInt(value[5])
        value = (r, g, b)
        falseColor = value
    if property == "hueShift":
        global hueShift
        hueShift = int(value)
    if property == "hue":
        global hue
        hue = int(value)
    if property == "saturation":
        global saturation
        saturation = int(value)
    if property == "lightness":
        global lightness
        lightness = int(value)
    if property == "currentMode":
        global currentMode
        currentMode = int(value)
    if property == "songOption":
        midiFile = value + ".mid"
        currentMode = 0
        progressFile = f"./progress/{profile}/{midiFile[:-4]}.csv"
        updateCSV(progressFile)
        time.sleep(0.2)
        currentMode = 1

    return Response(None, status=200)

@app.route('/updateFile', methods=['POST'])
def upload_file():
    if request.method == 'POST':
        # Check if the POST request has the file part
        if 'file' not in request.files:
            return "No file part", 400
        
        file = request.files['file']

        # If the user submits an empty part without a filename
        if file.filename == '':
            return "No selected file", 400

        if file:
            # Save the file to the specified directory
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], file.filename))
            global midiFile
            midiFile = file.filename
            global currentMode
            currentMode = 1
            global profile
            progressFile = f"./progress/{profile}/{midiFile[:-4]}.csv"
            if not os.path.exists(progressFile):
                # If the file doesn't exist, create a new file
                with open(progressFile, 'w') as f:
                    f.write('Timestamp,Accuracy\n')
            
            time.sleep(0.2)
            updateCSV(progressFile)
            updateSong()

            return f"File '{file.filename}' uploaded successfully", 200

@app.route('/data', methods=['GET'])
def getData():
    global percentage
    global midiFile
    global accuracy
    global currentMode
    global hue
    global saturation
    global lightness
    global hueCycling
    global lightPreset
    global tempTable
    global tempFileList
    global profile
    data = {
        'currentSongPercent': percentage,
        'currentSong': midiFile if currentMode == 1 else '-',
        'accuracy': accuracy if currentMode == 1 else '-',
        'currentMode': currentMode,
        'currentHue': hue,
        'currentSaturation': saturation,
        'currentLightness': lightness,
        'hueCycling': hueCycling,
        'lightPreset': lightPreset,
        'progress': tempTable,
        'songList': tempFileList,
        'profile': profile
    }
    tempTable = None
    tempFileList = None
    return jsonify(data)

def webServer():
    # Create the upload directory if it doesn't exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.use_reloader=False
    app.run(host='0.0.0.0', port=8000)


# -------------------------------------------- MAIN  FUNCTION -------------------------------------------- #
if __name__ == "__main__":
    
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    t3 = threading.Thread(target = webServer)
    t2 = threading.Thread(target = midiFilePlayer)
    t1 = threading.Thread(target = midiThread)

    t3.start()
    t2.start()
    t1.start()
    t1.join()
    t2.join()
    t3.join()