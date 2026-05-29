import math
import time
import threading
import numpy as np
import random
from scipy.signal import windows
from scipy.constants import G
from dataclasses import dataclass, field
from typing import Optional
import sounddevice as sd

#____CONSTANTS__________________________________________________________________
SAMPLE_RATE = 44100
CHANNELS =  2
BUFFER_SIZE = 512
MAX_VOICES = 2048

GRAVITY = 1000
WAVEFORM_SIZE = 2048

#____Physics Classes____________________________________________________________

@dataclass
class Planet:
    #Fixed gravitational well
    name:str
    x:float
    y:float
    mass: int
    radius:int
    numToPlay: int
    alreadyCollided: list[Asteroid]

    def __init__(self, name, x, y, radius):
        self.name = name
        self.x = x
        self.y = y
        self.radius = radius
        self.mass = radius**2
        self.numToPlay = 0
        self.pulse_events = 0
        self.alreadyCollided = []

    def __hash__(self):
        return hash(self.name)
    
    def __eq__(self, other):
        return self.name == other.name
    
    def getInRadius(self, a: Asteroid):
        dx = self.x - a.pX
        dy = self.y - a.pY
        r = math.sqrt(dx**2 + dy**2)
        return (r < self.radius)

@dataclass
class Asteroid:
    #Will orbit around one or multiple planets
    name: str
    vX: float
    vY: float
    pX: float
    pY: float

    def __init__(self, name, vX, vY, pX, pY):
        self.name = name
        self.vX = vX
        self.vY = vY
        self.pX = pX
        self.pY = pY

    def __hash__(self):
        return hash(self.name)

    def tick(self, timeDelta:float, planets:list[Planet], width:int, height:int):
        #Calculate the gravity from each planet
        #THE PHYSICS IS JANK I KNOW
        aX = 0.0
        aY = 0.0
        tempPx = 0.0
        tempPy = 0.0
        for p in planets:
            xDist = p.x - self.pX
            yDist = p.y - self.pY
            r = math.sqrt(xDist**2 + yDist**2)
            #If we are inside the planet, set these variables to play a sound
            if r < p.radius:
                if not p.alreadyCollided.__contains__(self):
                    p.numToPlay += 1
                    p.pulse_events += 1
                    p.alreadyCollided.append(self)
                continue
            if p.alreadyCollided.__contains__(self):
                p.alreadyCollided.remove(self)
            theta = math.atan2(yDist, xDist)
            g = GRAVITY * p.mass / r**2
            aX += g * math.cos(theta)
            aY += g * math.sin(theta)
        self.vX += aX * timeDelta
        self.vY += aY * timeDelta
        tempPx = self.pX + (self.vX * timeDelta)
        tempPy = self.pY + (self.vY * timeDelta)
        #If the asteroid is going to be off the screen, flip its velocity and re-do the calculation
        if tempPx < 0 or tempPx > width:
            self.vX = self.vX * -1
        self.pX += self.vX * timeDelta
        if tempPy < 0 or tempPy > height:
            self.vY = self.vY * -1
        self.pY += self.vY * timeDelta
        #print(self.name + ": Vx - " + str(self.vX) + "\tVy - " + str(self.vY))


#____Audio Manager___________________________________________________________
class AudioManager:
    def __init__(self, sampleRate: int = SAMPLE_RATE):
        self.sampleRate = sampleRate
        #Contains the sounds we want loaded in
        self.sounds: dict[str, np.array] = {}
        self.voices: list[list] = []
        self.lock = threading.Lock()
        self.stream: sd.OutputStream | None = None

        self.waveform_data = np.zeros(WAVEFORM_SIZE, dtype=np.float32)

        self.sounds["default"] = self.makeSine(240.0, 0.05)
        self.sounds["441"] = self.makeSine(232.0, 0.05)
        self.sounds["442"] = self.makeSine(248.0, 0.05)
        self.sounds["443"] = self.makeSine(224.0, 0.05)
        self.sounds["444"] = self.makeSine(256.0, 0.05)
        self.sounds["445"] = self.makeSine(232.0, 0.05)

    #Audio Library
    def makeSine(self, freq: float, duration: float) -> np.array:
        #My signals processing needs work sorry
        numSamples = int(self.sampleRate * duration)
        #Creates an array of sorts of how many samp
        time = np.linspace(0, duration, numSamples, endpoint=False)
        #Calculate the sine wave into an array of 32 bit floats
        #Using cosine to start at 1 LOL shhhhh
        wave = np.cos(2 * np.pi * freq * time).astype(np.float32)
        #Apply a hann window for smoothing (I think)
        wave = wave * windows.hann(numSamples).astype(np.float32)
        #Return a 1D array with our samples
        return np.column_stack([wave, wave])
    
    #Playback
    def play(self, volume:float, soundName: str="default"):
        if soundName not in self.sounds:
            return
        vox = [self.sounds[soundName], 0, volume]
        with self.lock:
            self.voices.append(vox)
            if len(self.voices) > MAX_VOICES:
                self.voices = self.voices[-MAX_VOICES:]

    def callback(self, out: np.array, frames: int, timeInfo, status):
        mix = np.zeros((frames, CHANNELS), dtype = np.float32)
        with self.lock:
            still_alive = []
            for v in self.voices:
                sample, iterator, volume = v
                chunk = sample[iterator : iterator + frames] * volume
                if len(chunk) == 0:
                    continue
                mix[0 : len(chunk)] += chunk
                v[1] += len(chunk)
                if v[1] < len(sample):
                    still_alive.append(v)
            self.voices = still_alive
        np.clip(mix, -1.0, 1.0, out=mix)
        out[:] = mix
        mono = (mix[:, 0] + mix[:, 1]) * 0.5
        self.waveform_data = np.roll(self.waveform_data, -frames)
        self.waveform_data[-frames:] = mono

    def startThread(self):
        self.stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32", blocksize=BUFFER_SIZE, callback=self.callback)
        self.stream.start()
        print("[Audio Manager] - started")

    def stopThread(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
            print("[Audio Manager] - stopped")

#____Engine_____________________________________________________________________
class Engine:
    def __init__(self, tick_rate: int = 120):
        self.asteroids: list[Asteroid] = []
        self.planets: list[Planet] = []
        self.tick_rate = tick_rate
        self.running = False
        self.thread = None
        self.width = 0
        self.height = 0
        self.audioManager = AudioManager()
    
    def add_planet(self, planet: Planet):
        self.planets.append(planet)
        return self
    
    def add_asteroid(self, asteroid: Asteroid):
        self.asteroids.append(asteroid)
        return self
    
    def start(self):
        self.audioManager.startThread()
        self.running = True
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        print(f"[Engine] started - {len(self.planets)} planets")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        self.audioManager.stopThread()
        print("[Engine] stopped")
    
    def loop(self):
        deltaTime = 1.0/self.tick_rate
        numTicks = 0
        soundsDict = ["default", "441", "442", "443", "444", "445"]
        while self.running:
            initTime = time.perf_counter()
            for a in self.asteroids:
                a.tick(deltaTime, self.planets, self.width, self.height)
                numTicks += 1
            #THIS CHECK MIGHT SLOW THINGS DOWN, LOOK TO OPTIMIZE IN THE FUTURE
            #Get how many total blips we're playing for volume's sake
            totalBlips = 0
            for p in self.planets:
                totalBlips += p.numToPlay
            if totalBlips > 0:
                volume = 1.0 / totalBlips
            else:
                volume = 1.0
            while totalBlips > 0:
                randNum = random.randint(0,5)
                self.audioManager.play(volume, soundsDict[randNum])
                totalBlips -= 1
            timeElapsed = time.perf_counter() - initTime
            sleep = max(0.0, deltaTime - timeElapsed)
            time.sleep(sleep)

    #____EXTRA PHYSICS FUNCTIONS________________________________________________________

    def runPotentialAsteroidSimulation(self, startPx:int, startPy:int, startVx:float, startVy:float, timeDelta:float):
        endState = [0,0,0,0]
        aX = 0.0
        aY = 0.0
        vX = startVx
        vY = startVy
        pX = startPx
        pY = startPy
        for p in self.planets:
            xDist = p.x - pX
            yDist = p.y - pY
            r = math.sqrt(xDist**2 + yDist**2)
            #If we are inside the planet, don't do anything
            if r < p.radius:
                continue
            theta = math.atan2(yDist, xDist)
            g = GRAVITY * p.mass / r**2
            aX += g * math.cos(theta)
            aY += g * math.sin(theta)
        vX += aX * timeDelta
        vY += aY * timeDelta
        tempPx = pX + (vX * timeDelta)
        tempPy = pY + (vY * timeDelta)
        #If the asteroid is going to be off the screen, flip its velocity
        if tempPx < 0 or tempPx > self.width:
            vX = vX * -1
        pX += vX * timeDelta
        if tempPy < 0 or tempPy > self.height:
            vY = vY * -1
        pY += vY * timeDelta
        endState[0] = pX
        endState[1] = pY
        endState[2] = vX
        endState[3] = vY
        return endState
