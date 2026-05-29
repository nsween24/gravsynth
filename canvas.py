import math
import time
import threading
from collections import deque
import pygame
import pygame.gfxdraw
import numpy as np
from engine import Engine, Planet, Asteroid #, AudioSource

#____CONSTANTS_________________________________________________________________
WIDTH, HEIGHT = 960, 640
PANEL_WIDTH = 100
FPS = 60
MODE_NORMAL = 0
MODE_ADDPLANET = 1
MODE_ADDASTEROID = 2

TRAIL_LENGTH = 50
POTENTIAL_AST_SEGMENTS = 100
PULSE_DURATION = 0.6        # seconds a pulse ring expands for
WAVEFORM_HEIGHT = 80        # px reserved at the bottom for the waveform

#____Palette___________________________________________________________________
GRID = (18, 18, 30)
BACKGROUND = (0,0,6)
PANEL_BG = (20, 20, 38, 160) #opacity is 160
TEXT_COLOR = (255, 255, 255)
BUTTON_CLR = (128, 128, 255)
BUTTON_HOV = (255, 255, 128)
PANEL_BORDER = (60, 60, 100)
ASTEROID_COLOR = (255, 0, 0)
ASTEROID_POTENTIAL_COLOR = (255, 255, 255)
WAVEFORM_COLOR = (80, 220, 120)
WAVEFORM_BG = (0, 8, 0, 190)
WAVEFORM_LINE = (30, 60, 30)

#____GUI Helpers______________________________________________________________-
def drawRectAlpha(surf, colorRGBA, rect):
    surface = pygame.Surface((rect[2], rect[3]), pygame.SRCALPHA)
    surface.fill(colorRGBA)
    surf.blit(surface, (rect[0], rect[1]))

def stick(value, low, high):
    return max(low, min(high, value))

#____GUI Objects________________________________________________________________
class Button:
    def __init__(self, x, y, w, h, label, color=BUTTON_CLR, hoverColor = BUTTON_HOV, font=None):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.color = color
        self.hoverColor = hoverColor
        self.font = font
        self.isHovered = False

    def update(self, mousePos):
        self.isHovered = self.rect.collidepoint(mousePos)

    def draw(self, surf):
        color = self.color
        if self.isHovered:
            color = self.hoverColor
        drawRectAlpha(surf, (color[0], color[1], color[2], 210), self.rect)
        pygame.draw.rect(surf, PANEL_BORDER, self.rect, 1, border_radius = 4)
        if self.font:
            labl = self.font.render(self.label, True, TEXT_COLOR)
            surf.blit(labl, labl.get_rect(center=self.rect.center))

    def clicked(self, event):
        return (event.type == pygame.MOUSEBUTTONDOWN and
                event.button == 1 and
                self.rect.collidepoint(event.pos))


#____SIDE PANEL______________________________________________________________

class SidePanel:
    panelX = WIDTH - PANEL_WIDTH       # left edge of panel in window coords

    def __init__(self, engine: Engine, canvas: "Canvas"):
        self.engine  = engine
        self.canvas  = canvas

        pygame.font.init()
        self.font_hd  = pygame.font.SysFont("monospace", 13, bold=True)
        self.font_sm  = pygame.font.SysFont("monospace", 11)
        self.font_btn = pygame.font.SysFont("monospace", 11, bold=True)

        self.buildUi()

    #____Main UI Creation Function______________________________________________
    def buildUi(self):
        xPad = self.panelX + 10
        yPad = 10
        w = PANEL_WIDTH - 20
        h = 40
        #Add planet button
        self.button_addPlanet = Button(xPad, yPad, w, h, "Add\nPlanet", BUTTON_CLR, BUTTON_HOV, self.font_btn)
        yPad += h + 10
        #Add asteroid button
        self.button_addAsteroid = Button(xPad, yPad, w, h, "Add\nAsteroid", BUTTON_CLR, BUTTON_HOV, self.font_btn)
        yPad += h + 10

    def update(self, mousePos):
        self.button_addPlanet.update(mousePos)
        self.button_addAsteroid.update(mousePos)


    #____Draw Side Panel__________________________________________________________
    def draw(self, surf):
        #Panel itself
        drawRectAlpha(surf, PANEL_BG, (self.panelX, 0, PANEL_WIDTH, HEIGHT))
        #Buttons
        self.button_addPlanet.draw(surf)
        self.button_addAsteroid.draw(surf)



#____Canvas____________________________________________________________________
class Canvas:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.mode = MODE_NORMAL
        self.trails = {}           # asteroid.name -> deque of (x, y)
        self.planet_pulses = {}    # planet.name   -> list of start times

    #____Drawing Functions___________________________________________________
    def draw_grid(self, surf):
        for x in range(0, WIDTH, 10):
            pygame.draw.line(surf, GRID, (x,0), (x,HEIGHT))
        for y in range(0, HEIGHT, 10):
            pygame.draw.line(surf, GRID, (0,y), (WIDTH,y))

    def draw_planet(self, surf, planet, now):
        # Pulse rings (drawn behind the planet)
        for start in self.planet_pulses.get(planet.name, []):
            progress = (now - start) / PULSE_DURATION
            if progress >= 1.0:
                continue
            pulse_r = round(planet.radius + (planet.radius + 28) * progress)
            alpha = int(210 * (1.0 - progress))
            size = (pulse_r + 2) * 2
            s = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.gfxdraw.aacircle(s, size // 2, size // 2, pulse_r, (255, 255, 255, alpha))
            surf.blit(s, (round(planet.x) - size // 2, round(planet.y) - size // 2))

        pygame.gfxdraw.filled_circle(surf, round(planet.x), round(planet.y), planet.radius, (255,255,255))
        pygame.gfxdraw.aacircle(surf, round(planet.x), round(planet.y), planet.radius, (255,255,255))

    def draw_asteroid(self, surf, asteroid):
        trail = self.trails.get(asteroid.name)
        if trail:
            n = len(trail)
            for i, (tx, ty) in enumerate(trail):
                t = (i + 1) / n  # 0=oldest, 1=newest
                r = int(BACKGROUND[0] + (ASTEROID_COLOR[0] - BACKGROUND[0]) * t)
                g = int(BACKGROUND[1] + (ASTEROID_COLOR[1] - BACKGROUND[1]) * t)
                b = int(BACKGROUND[2] + (ASTEROID_COLOR[2] - BACKGROUND[2]) * t)
                pygame.gfxdraw.filled_circle(surf, round(tx), round(ty), 1, (r, g, b))
        pygame.gfxdraw.filled_circle(surf, round(asteroid.pX), round(asteroid.pY), 2, ASTEROID_COLOR)

    def draw_waveform(self, surf):
        wform_y = HEIGHT - WAVEFORM_HEIGHT
        wform_w = WIDTH - PANEL_WIDTH

        drawRectAlpha(surf, WAVEFORM_BG, (0, wform_y, wform_w, WAVEFORM_HEIGHT))
        pygame.draw.line(surf, WAVEFORM_LINE, (0, wform_y), (wform_w, wform_y), 1)

        data = self.engine.audioManager.waveform_data
        n = len(data)
        if n == 0:
            return

        indices = np.linspace(0, n - 1, wform_w).astype(int)
        samples = data[indices]

        mid_y = wform_y + WAVEFORM_HEIGHT // 2
        half_h = WAVEFORM_HEIGHT // 2 - 6

        points = [(i, int(mid_y - float(samples[i]) * half_h)) for i in range(wform_w)]
        if len(points) > 1:
            pygame.draw.lines(surf, WAVEFORM_COLOR, False, points, 1)

    def draw_potentialBody(self, surf, mousePos, radius, color):
        pygame.gfxdraw.filled_circle(surf, mousePos[0], mousePos[1], radius, color)

    def draw_potentialAsteroidTrajectory(self, surf, mousePos, color):
        pX = mousePos[0]
        pY = mousePos[1]
        vX = 0
        vY = 0
        for i in range(POTENTIAL_AST_SEGMENTS):
            #Calculate the trajectory for 100 ticks
            dT = 1.0 / self.engine.tick_rate
            startCoords = [pX, pY]
            results = self.engine.runPotentialAsteroidSimulation(pX, pY, vX, vY, dT)
            pX = results[0]
            pY = results[1]
            vX = results[2]
            vY = results[3]
            #Draw the line from startCoords to pX, pY
            


    #__Main Loop_______________________________________________________________
    def run(self):
        pygame.init()
        surf = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Gravity")
        clock = pygame.time.Clock()

        panel = SidePanel(self.engine, self)

        self.engine.start()
        running = True
        last_time = time.perf_counter()
        gameMode = MODE_NORMAL

        numCanvasDraws = 0
        potentialPlanetRadius = 10
        while running:
            now = time.perf_counter()
            deltaTime = now - last_time
            last_time = now

            #EVENT HANDLER
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                #KEYSTROKES
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False

                #SCROLL WHEEL
                if event.type == pygame.MOUSEWHEEL:
                    ##event.y is the distance we scroll
                    potentialPlanetRadius += event.y
                    if potentialPlanetRadius <= 0:
                        potentialPlanetRadius = 1


                #MOUSE CLICKS
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if panel.button_addPlanet.clicked(event):
                        gameMode = MODE_ADDPLANET
                    if panel.button_addAsteroid.clicked(event):
                        gameMode = MODE_ADDASTEROID

                    if event.button == 3: #RIGHT CLICK
                        gameMode = MODE_NORMAL

                    if event.button == 1: #LEFT CLICK
                        if gameMode == MODE_ADDPLANET:
                            #Add Planet
                            if mousePos[0] < WIDTH - PANEL_WIDTH:
                                planetName = "p" + str(len(engine.planets) + 1)
                                engine.add_planet(Planet(planetName, mousePos[0], mousePos[1], potentialPlanetRadius))
                        elif gameMode == MODE_ADDASTEROID:
                            #Add Asteroid
                            if mousePos[0] < WIDTH - PANEL_WIDTH:
                                asteroidName = "a" + str(len(engine.asteroids) + 1)
                                engine.add_asteroid(Asteroid(asteroidName, 0, 0, mousePos[0], mousePos[1]))


            #Updates
            mousePos = pygame.mouse.get_pos()
            panel.update(mousePos)

            # Update asteroid trails
            for a in self.engine.asteroids:
                if a.name not in self.trails:
                    self.trails[a.name] = deque(maxlen=TRAIL_LENGTH)
                self.trails[a.name].append((a.pX, a.pY))

            # Consume planet pulse events and expire old pulses
            for p in self.engine.planets:
                if p.name not in self.planet_pulses:
                    self.planet_pulses[p.name] = []
                while p.pulse_events > 0:
                    self.planet_pulses[p.name].append(now)
                    p.pulse_events -= 1
                self.planet_pulses[p.name] = [
                    t for t in self.planet_pulses[p.name] if now - t < PULSE_DURATION
                ]

            #RENDERER
            surf.fill(BACKGROUND)
            #self.draw_grid(surf)

            # Trails (drawn before planets so they sit underneath)
            for a in self.engine.asteroids:
                self.draw_asteroid(surf, a)

            #Planets (with pulse rings)
            for p in self.engine.planets:
                self.draw_planet(surf, p, now)

            # Waveform overlay
            self.draw_waveform(surf)

            #GUI Panel
            panel.draw(surf)

            #Mode drawer
            if gameMode == MODE_ADDASTEROID:
                self.draw_potentialBody(surf, mousePos, 1, (255,0,0))
            if gameMode == MODE_ADDPLANET:
                self.draw_potentialBody(surf, mousePos, potentialPlanetRadius, (255,255,255))


            numCanvasDraws += 1
            #print("Canvas Draws: " + str(numCanvasDraws))
            pygame.display.flip()
            clock.tick(FPS)

        #LOOP EXITED
        self.engine.stop()
        pygame.quit()

#____APPLICATION ENTRY_________________________________________________________

if __name__ == "__main__":
    #Define planets
    p1 = Planet("p1", 400, 400, 10)
    a1 = Asteroid("a1", -20, 0, 450, 500)
    p2 = Planet("p2", 600, 100, 50)
    #Set up engine and canvas
    engine = (
    Engine(tick_rate=60)
        .add_planet(p1)
        .add_planet(p2)
        .add_asteroid(a1)
    )
    engine.width = WIDTH - PANEL_WIDTH
    engine.height = HEIGHT
    canvas = Canvas(engine)
    canvas.run()
