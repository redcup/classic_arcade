#!/usr/bin/env python3
"""
ASTEROIDS - a polished, feature-rich arcade blaster in pure Python + pygame.

Features
--------
* Smooth 60 FPS physics: thrust, inertia, friction, wrap-around space
* Three sizes of procedurally shaped, spinning asteroids that split when shot
* Particle explosions, engine flames, screen shake, parallax twinkling starfield
* Endless waves with escalating difficulty + wave-clear bonuses
* Asteroids get faster with every wave (up to 3x)
* Enemy flying saucer from wave 2: zigzags, snipes you, 150/300 pts
* Power-ups: RAPID fire, SPREAD shot, SHIELD, BOMB (limited, press B)
* Nuke that clears the screen, high score saved to disk, extra life every 10k
* Score pop-ups, full HUD (lives, bombs, power-up timers), slow-mo on death
* Menu, pause and game-over screens, F11 fullscreen toggle
* All sound effects are synthesized at runtime in pure Python
  (no asset files, no extra dependencies); silent only if no audio device

Controls
--------
  LEFT / RIGHT (or A / D)   rotate
  UP (or W)                 thrust
  SPACE                     fire (hold for auto-fire)
  B                         detonate bomb
  P                         pause
  F11                       toggle fullscreen
  ESC                       back to menu / quit
  ENTER                     start / play again

Run:             python asteroids.py
Headless check:  python asteroids.py --selftest [frames]
"""

import array
import json
import math
import os
import random
import sys

SELFTEST = "--selftest" in sys.argv
SELFTEST_FRAMES = 600
if SELFTEST:
    i = sys.argv.index("--selftest")
    if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
        SELFTEST_FRAMES = int(sys.argv[i + 1])
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402  (env vars must be set before this import)

WIDTH, HEIGHT = 960, 720
FPS = 60
TAU = math.tau

HS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "asteroids_highscore.json")


def load_highscore():
    try:
        with open(HS_FILE) as f:
            return int(json.load(f).get("highscore", 0))
    except Exception:
        return 0


def save_highscore(v):
    try:
        with open(HS_FILE, "w") as f:
            json.dump({"highscore": int(v)}, f)
    except Exception:
        pass


def wrap(p, m=40):
    """Wrap a mutable [x, y] position around the screen with margin m."""
    if p[0] < -m:
        p[0] += WIDTH + 2 * m
    elif p[0] > WIDTH + m:
        p[0] -= WIDTH + 2 * m
    if p[1] < -m:
        p[1] += HEIGHT + 2 * m
    elif p[1] > HEIGHT + m:
        p[1] -= HEIGHT + 2 * m


def wdist2(a, b):
    """Squared distance between two points, aware of screen wrapping."""
    dx = abs(a[0] - b[0])
    dx = min(dx, WIDTH - dx)
    dy = abs(a[1] - b[1])
    dy = min(dy, HEIGHT - dy)
    return dx * dx + dy * dy


# ------------------------------------------------------------------ sound --

class SFX:
    """Synthesizes all sound effects in pure Python at startup (no asset
    files, no numpy required); degrades to silence if no audio device."""

    def __init__(self):
        self.ok = False
        self.sounds = {}
        self.thrust_sound = None
        self.thrust_playing = False
        try:
            pygame.mixer.pre_init(44100, -16, 1, 512)
        except Exception:
            pass

    def build(self):
        init = pygame.mixer.get_init()
        if init is None:
            try:
                pygame.mixer.init(44100, -16, 1, 512)
            except pygame.error:
                return
            init = pygame.mixer.get_init()
        if init is None:
            return
        SR, _fmt, ch = init  # use the real device rate so pitch is correct

        def tone(freq, dur, to=None):
            n = max(2, int(SR * dur))
            out = array.array("h")
            phase = 0.0
            f = float(freq)
            df = ((to if to is not None else freq) - freq) / n
            for i in range(n):
                f += df
                phase += 6.283185307179586 * f / SR
                out.append(int(math.sin(phase) * math.exp(-4.0 * i / n) * 32767))
            return out

        def noise(dur, lp=0.15, decay=2.0, seed=None):
            n = max(2, int(SR * dur))
            rng = random.Random(seed)
            out = array.array("h")
            acc = 0.0
            for i in range(n):
                acc += lp * (rng.uniform(-1.0, 1.0) - acc)
                out.append(int(acc * math.exp(-decay * i / n) * 32767))
            return out

        def join(*parts):
            out = array.array("h")
            for p in parts:
                out.extend(p)
            return out

        def mk(samples, vol):
            # Normalize to a consistent loudness, then emit 16-bit PCM.
            peak = max(abs(v) for v in samples) or 1
            k = vol * 32767 / peak
            out = array.array("h")
            for v in samples:
                s = max(-32767, min(32767, int(v * k)))
                out.append(s)
                if ch == 2:
                    out.append(s)  # duplicate mono -> stereo
            return pygame.mixer.Sound(buffer=out.tobytes())

        self.sounds["laser"] = mk(tone(950, 0.09, 220), 0.30)
        self.sounds["e1"] = mk(noise(0.22, 0.30, 2.0), 0.50)
        self.sounds["e2"] = mk(noise(0.35, 0.20, 2.2), 0.65)
        self.sounds["e3"] = mk(noise(0.50, 0.12, 2.6), 0.80)
        self.sounds["boom"] = mk(noise(0.90, 0.07, 3.0), 0.95)
        self.sounds["power"] = mk(join(tone(500, 0.07), tone(760, 0.10)), 0.40)
        self.sounds["shield"] = mk(tone(200, 0.30, 520), 0.40)
        self.sounds["jingle"] = mk(join(tone(660, 0.09), tone(880, 0.09),
                                        tone(1320, 0.16)), 0.40)
        self.sounds["saucer"] = mk(join(tone(310, 0.11), tone(415, 0.11)), 0.25)
        self.sounds["sshoot"] = mk(tone(700, 0.09, 1400), 0.35)
        self.thrust_sound = mk(noise(0.25, 0.12, 1.0, seed=7), 0.25)
        self.ok = True

    def play(self, name):
        if self.ok and name in self.sounds:
            self.sounds[name].play()

    def set_thrust(self, on):
        if not self.ok:
            return
        if on and not self.thrust_playing:
            self.thrust_sound.play(loops=-1)
            self.thrust_playing = True
        elif not on and self.thrust_playing:
            self.thrust_sound.fadeout(150)
            self.thrust_playing = False


# -------------------------------------------------------------- entities --

class Star:
    def __init__(self):
        self.x = random.uniform(0, WIDTH)
        self.y = random.uniform(0, HEIGHT)
        self.l = random.choice((0.25, 0.5, 1.0))
        self.ph = random.uniform(0, TAU)

    def update(self, dt, vx, vy):
        self.x -= vx * self.l * 0.08 * dt
        self.y -= vy * self.l * 0.08 * dt
        if self.x < -2:
            self.x += WIDTH + 4
        elif self.x > WIDTH + 2:
            self.x -= WIDTH + 4
        if self.y < -2:
            self.y += HEIGHT + 4
        elif self.y > HEIGHT + 2:
            self.y -= HEIGHT + 4

    def draw(self, s, t):
        b = int((40 + 150 * self.l) * (0.7 + 0.3 * math.sin(t * 2.5 + self.ph)))
        b = max(0, min(255, b))
        sz = 2 if self.l == 1.0 else 1
        s.fill((b, b, min(255, int(b * 1.15))), (int(self.x), int(self.y), sz, sz))


class Particle:
    __slots__ = ("pos", "vel", "t", "life", "color", "size")

    def __init__(self, pos, vel, life, color, size):
        self.pos = [pos[0], pos[1]]
        self.vel = [vel[0], vel[1]]
        self.t = life
        self.life = life
        self.color = color
        self.size = size

    def update(self, dt):
        self.pos[0] += self.vel[0] * dt
        self.pos[1] += self.vel[1] * dt
        f = math.exp(-2.5 * dt)
        self.vel[0] *= f
        self.vel[1] *= f
        self.t -= dt

    def draw(self, s):
        k = max(self.t / self.life, 0.0)
        c = (int(self.color[0] * k), int(self.color[1] * k), int(self.color[2] * k))
        pygame.draw.circle(s, c, (int(self.pos[0]), int(self.pos[1])), max(1, int(self.size * k)))


class Popup:
    def __init__(self, pos, text, color):
        self.pos = [pos[0], pos[1]]
        self.text = text
        self.color = color
        self.t = 1.0

    def update(self, dt):
        self.pos[1] -= 26 * dt
        self.t -= dt

    def draw(self, s, f):
        k = max(min(self.t, 1.0), 0.0)
        c = (int(self.color[0] * k), int(self.color[1] * k), int(self.color[2] * k))
        t = f.render(self.text, True, c)
        s.blit(t, t.get_rect(center=(int(self.pos[0]), int(self.pos[1]))))


class Bullet:
    def __init__(self, pos, vel):
        self.pos = [pos[0], pos[1]]
        self.vel = [vel[0], vel[1]]
        self.t = 1.05

    def update(self, dt):
        self.pos[0] += self.vel[0] * dt
        self.pos[1] += self.vel[1] * dt
        wrap(self.pos, 8)
        self.t -= dt

    def draw(self, s):
        pygame.draw.circle(s, (110, 160, 255), (int(self.pos[0]), int(self.pos[1])), 4)
        pygame.draw.circle(s, (255, 255, 255), (int(self.pos[0]), int(self.pos[1])), 2)


class Asteroid:
    RADII = {3: 34, 2: 22, 1: 12}

    def __init__(self, pos, vel, size):
        self.pos = [pos[0], pos[1]]
        self.vel = [vel[0], vel[1]]
        self.size = size
        self.radius = self.RADII[size]
        n = random.randint(9, 13)
        self.shape = [random.uniform(0.72, 1.18) for _ in range(n)]
        self.angle = random.uniform(0, TAU)
        self.spin = random.uniform(-1.6, 1.6)
        self.tone = random.randint(140, 205)

    @property
    def speed(self):
        return math.hypot(self.vel[0], self.vel[1])

    def update(self, dt):
        self.pos[0] += self.vel[0] * dt
        self.pos[1] += self.vel[1] * dt
        self.angle += self.spin * dt
        wrap(self.pos, 50)

    def points(self):
        out = []
        n = len(self.shape)
        for i in range(n):
            a = self.angle + i / n * TAU
            r = self.radius * self.shape[i]
            out.append((self.pos[0] + r * math.cos(a),
                        self.pos[1] + r * math.sin(a)))
        return out

    def draw(self, s):
        c = (self.tone, self.tone, int(self.tone * 1.05))
        pygame.draw.polygon(s, c, self.points(), 2)


KIND_COLORS = {"RAPID": (255, 220, 60), "SPREAD": (255, 150, 60),
               "SHIELD": (80, 220, 255), "BOMB": (255, 90, 130)}


class PowerUp:
    def __init__(self, pos, kind):
        self.pos = [pos[0], pos[1]]
        self.kind = kind
        self.color = KIND_COLORS[kind]
        self.t = 10.0
        self.spin = random.uniform(0, TAU)

    def update(self, dt):
        self.t -= dt
        self.spin += dt * 3
        wrap(self.pos, 16)

    def draw(self, s, f):
        if self.t < 3 and int(self.t * 6) % 2 == 0:
            return
        x, y = int(self.pos[0]), int(self.pos[1])
        r = 11 + math.sin(self.spin * 2) * 1.5
        pts = [(x, y - r), (x + r, y), (x, y + r), (x - r, y)]
        pygame.draw.polygon(s, self.color, pts, 2)
        t = f.render(self.kind[0], True, self.color)
        s.blit(t, t.get_rect(center=(x, y)))


class SaucerBullet:
    def __init__(self, pos, vel):
        self.pos = [pos[0], pos[1]]
        self.vel = [vel[0], vel[1]]
        self.t = 1.6

    def update(self, dt):
        self.pos[0] += self.vel[0] * dt
        self.pos[1] += self.vel[1] * dt
        wrap(self.pos, 8)
        self.t -= dt

    def draw(self, s):
        pygame.draw.circle(s, (255, 70, 90), (int(self.pos[0]), int(self.pos[1])), 4)
        pygame.draw.circle(s, (255, 220, 220), (int(self.pos[0]), int(self.pos[1])), 2)


class Saucer:
    """The flying saucer: darts across, zigzags, and snipes the player."""

    def __init__(self):
        from_left = random.random() < 0.5
        self.pos = [(-50 if from_left else WIDTH + 50),
                    random.uniform(HEIGHT * 0.15, HEIGHT * 0.85)]
        self.vx = (65 if from_left else -65) * random.uniform(0.9, 1.3)
        self.base_y = self.pos[1]
        self.t = 0.0
        self.fire_cd = random.uniform(0.8, 1.6)
        self.siren_cd = 0.4
        self.radius = 18

    def update(self, dt, ship, game):
        self.t += dt
        self.pos[0] += self.vx * dt
        self.pos[1] = self.base_y + math.sin(self.t * 3.4) * 55
        if game.state != "play":
            return
        self.fire_cd -= dt
        if self.fire_cd <= 0 and ship.alive and ship.invincible <= 0:
            self.fire_cd = random.uniform(1.0, 1.8)
            ang = wrapped_aim(self.pos, ship.pos) + random.uniform(-0.08, 0.08)
            game.saucer_bullets.append(SaucerBullet(
                self.pos, [math.cos(ang) * 420, math.sin(ang) * 420]))
            game.sfx.play("sshoot")
        self.siren_cd -= dt
        if self.siren_cd <= 0:
            self.siren_cd = 0.55
            game.sfx.play("saucer")

    def draw(self, s):
        x, y = int(self.pos[0]), int(self.pos[1])
        c1 = (160, 170, 210)
        pygame.draw.ellipse(s, c1, (x - 20, y - 5, 40, 11), 2)    # hull
        pygame.draw.ellipse(s, c1, (x - 9, y - 14, 18, 11), 2)    # dome
        for i in range(3):
            on = (int(self.t * 6) + i) % 3 == 0
            pygame.draw.rect(s, (255, 200, 80) if on else (90, 95, 120),
                             (x - 11 + i * 10, y, 4, 4))


class Ship:
    def __init__(self):
        self.pos = [WIDTH / 2, HEIGHT / 2]
        self.vel = [0.0, 0.0]
        self.angle = -math.pi / 2
        self.alive = True
        self.invincible = 2.0
        self.fire_cd = 0.0
        self.thrusting = False
        self.rapid = 0.0
        self.spread = 0.0
        self.shield = 0.0

    def transform(self, x, y):
        c, s = math.cos(self.angle), math.sin(self.angle)
        return (self.pos[0] + x * c - y * s, self.pos[1] + x * s + y * c)

    def draw(self, s):
        if not self.alive:
            return
        if self.invincible > 0 and int(self.invincible * 12) % 2 == 0:
            return
        if self.thrusting:
            fl = random.uniform(6, 15)
            a = self.transform(-7, 0)
            b = self.transform(-7 - fl, 0)
            pygame.draw.line(s, (255, 140, 40), a, b, 3)
            pygame.draw.line(s, (255, 230, 120), a, b, 1)
        pts = [self.transform(15, 0), self.transform(-11, 10),
               self.transform(-6, 0), self.transform(-11, -10)]
        pygame.draw.polygon(s, (232, 236, 246), pts, 2)
        pygame.draw.line(s, (120, 200, 255), self.transform(9, 0),
                         self.transform(-5, 0), 1)
        if self.shield > 0:
            pulse = 2 if self.shield < 2 else 0
            pygame.draw.circle(s, (80, 220, 255),
                               (int(self.pos[0]), int(self.pos[1])), 24 + pulse, 2)


# ------------------------------------------------------------------- game --

class Game:
    def __init__(self, screen, sfx):
        self.screen = screen
        self.sfx = sfx
        self.world = pygame.Surface((WIDTH, HEIGHT))
        self.f_huge = pygame.font.Font(None, 92)
        self.f_med = pygame.font.Font(None, 40)
        self.f_sm = pygame.font.Font(None, 24)
        self.f_tiny = pygame.font.Font(None, 18)
        self.highscore = load_highscore()
        self.stars = [Star() for _ in range(140)]
        self.time = 0.0
        self.state = "menu"
        self.menu_rocks = []
        self.new_menu_rocks()
        self.paused = False
        self.reset_play()

    # -- state transitions --------------------------------------------------

    def new_menu_rocks(self):
        self.menu_rocks = []
        for _ in range(7):
            a = Asteroid([random.uniform(0, WIDTH), random.uniform(0, HEIGHT)],
                         [random.uniform(-40, 40), random.uniform(-40, 40)],
                         random.randint(1, 3))
            self.menu_rocks.append(a)

    def reset_play(self):
        self.asteroids = []
        self.bullets = []
        self.particles = []
        self.popups = []
        self.powerups = []
        self.ship = Ship()
        self.score = 0
        self.lives = 3
        self.bombs = 1
        self.wave = 0
        self.wave_delay = 1.0
        self.wave_banner = 0.0
        self.next_life_at = 10000
        self.shake = 0.0
        self.slowmo = 0.0
        self.saucers = []
        self.saucer_bullets = []
        self.saucer_timer = random.uniform(14, 20)
        self.respawn_t = 0.0
        self.new_record = False
        self.over_t = 0.0
        self.paused = False
        self.state = "play"
        self.sfx.set_thrust(False)

    def start_game(self):
        self.reset_play()

    def to_menu(self):
        self.state = "menu"
        self.paused = False
        self.new_menu_rocks()
        self.sfx.set_thrust(False)

    def game_over(self):
        self.state = "over"
        self.over_t = 0.0
        self.sfx.set_thrust(False)
        if self.score > self.highscore:
            self.highscore = self.score
            self.new_record = True
            save_highscore(self.highscore)

    # -- spawning -----------------------------------------------------------

    @property
    def level_factor(self):
        # Asteroids get noticeably faster with every wave (capped at 3x).
        return min(1.0 + 0.12 * (self.wave - 1), 3.0)

    def next_wave(self):
        self.wave += 1
        self.wave_delay = None
        self.wave_banner = 2.2
        for _ in range(min(3 + self.wave, 10)):
            self.spawn_asteroid(3)

    def spawn_asteroid(self, size):
        for _ in range(60):
            side = random.randint(0, 3)
            if side == 0:
                p = [random.uniform(0, WIDTH), -45]
            elif side == 1:
                p = [random.uniform(0, WIDTH), HEIGHT + 45]
            elif side == 2:
                p = [-45, random.uniform(0, HEIGHT)]
            else:
                p = [WIDTH + 45, random.uniform(0, HEIGHT)]
            if wdist2(p, self.ship.pos) > 260 ** 2:
                break
        tx = random.uniform(WIDTH * 0.25, WIDTH * 0.75)
        ty = random.uniform(HEIGHT * 0.25, HEIGHT * 0.75)
        dx, dy = tx - p[0], ty - p[1]
        d = math.hypot(dx, dy) or 1.0
        sp = random.uniform(28, 60) * (1.05 - 0.12 * size) * self.level_factor
        self.asteroids.append(Asteroid(p, [dx / d * sp, dy / d * sp], size))

    def clear_spot(self, pos, radius):
        return all(wdist2(pos, a.pos) > (radius + a.radius) ** 2
                   for a in self.asteroids)

    # -- scoring ------------------------------------------------------------

    def add_score(self, n):
        self.score += n
        if self.score >= self.next_life_at:
            self.lives = min(self.lives + 1, 6)
            self.next_life_at += 10000
            self.popups.append(Popup([WIDTH / 2, HEIGHT / 2 - 70],
                                     "EXTRA LIFE!", (255, 230, 90)))
            self.sfx.play("jingle")

    # -- destruction ----------------------------------------------------------

    def explode(self, pos, radius, red=False):
        n = int(10 + radius * 0.8)
        palette = ([(255, 90, 70), (255, 160, 60), (255, 240, 200)] if red
                   else [(255, 255, 255), (255, 200, 120), (180, 190, 210)])
        for _ in range(n):
            ang = random.uniform(0, TAU)
            sp = random.uniform(20, 60 + radius * 2.2)
            self.particles.append(Particle(
                pos, [math.cos(ang) * sp, math.sin(ang) * sp],
                random.uniform(0.3, 0.85), random.choice(palette),
                random.uniform(1, 3)))

    def kill_asteroid(self, a, by_bomb=False):
        if a in self.asteroids:
            self.asteroids.remove(a)
        pts = 50 if by_bomb else {3: 20, 2: 50, 1: 100}[a.size]
        self.add_score(pts)
        if not by_bomb:
            self.popups.append(Popup(a.pos, str(pts), (200, 220, 255)))
        self.explode(a.pos, a.radius)
        self.shake = min(self.shake + {3: 8, 2: 5, 1: 3}[a.size], 18)
        self.sfx.play({3: "e3", 2: "e2", 1: "e1"}[a.size])
        if a.size > 1 and not by_bomb:
            base = math.atan2(a.vel[1], a.vel[0])
            for _ in range(2):
                ang = base + random.uniform(-1.1, 1.1)
                sp = a.speed * random.uniform(1.15, 1.5)
                self.asteroids.append(Asteroid(
                    [a.pos[0], a.pos[1]],
                    [math.cos(ang) * sp, math.sin(ang) * sp], a.size - 1))
        if not by_bomb and random.random() < {3: 0.04, 2: 0.08, 1: 0.14}[a.size]:
            self.powerups.append(PowerUp(a.pos, random.choice(list(KIND_COLORS))))

    def kill_saucer(self, sa):
        if sa in self.saucers:
            self.saucers.remove(sa)
        pts = 300 if self.wave >= 5 else 150
        self.add_score(pts)
        self.popups.append(Popup(sa.pos, str(pts), (200, 220, 255)))
        self.explode(sa.pos, 20)
        self.shake = min(self.shake + 5, 18)
        self.sfx.play("e2")
        if random.random() < 0.35:
            self.powerups.append(PowerUp(sa.pos, random.choice(list(KIND_COLORS))))

    def ship_explode(self):
        sh = self.ship
        sh.alive = False
        sh.thrusting = False
        self.sfx.set_thrust(False)
        self.explode(sh.pos, 30, red=True)
        self.shake = 14
        self.slowmo = 1.0
        self.sfx.play("e3")
        self.lives -= 1
        if self.lives <= 0:
            self.game_over()
        else:
            self.respawn_t = 2.0

    def nuke(self):
        if self.state != "play" or self.paused:
            return
        if self.bombs <= 0 or not self.asteroids:
            return
        self.bombs -= 1
        for a in list(self.asteroids):
            self.kill_asteroid(a, by_bomb=True)
        for sa in list(self.saucers):
            self.kill_saucer(sa)
        self.popups.append(Popup([WIDTH / 2, HEIGHT / 2 - 40], "NUKE!",
                                 (255, 120, 200)))
        self.shake = 22
        self.slowmo = 0.8
        self.sfx.play("boom")

    def collect(self, pu):
        sh = self.ship
        self.powerups.remove(pu)
        self.sfx.play("power")
        if pu.kind == "RAPID":
            sh.rapid = 8.0
            self.popups.append(Popup(sh.pos, "RAPID FIRE!", pu.color))
        elif pu.kind == "SPREAD":
            sh.spread = 8.0
            self.popups.append(Popup(sh.pos, "SPREAD SHOT!", pu.color))
        elif pu.kind == "SHIELD":
            sh.shield = 10.0
            self.popups.append(Popup(sh.pos, "SHIELD UP!", pu.color))
        else:
            self.bombs = min(self.bombs + 1, 3)
            self.popups.append(Popup(sh.pos, "BOMB +1", pu.color))

    def fire(self):
        sh = self.ship
        sh.fire_cd = 0.07 if sh.rapid > 0 else 0.22
        dirs = [sh.angle]
        if sh.spread > 0:
            dirs += [sh.angle - 0.18, sh.angle + 0.18]
        for d in dirs:
            nx = sh.pos[0] + math.cos(d) * 16
            ny = sh.pos[1] + math.sin(d) * 16
            self.bullets.append(Bullet(
                [nx, ny],
                [math.cos(d) * 640 + sh.vel[0], math.sin(d) * 640 + sh.vel[1]]))
        self.sfx.play("laser")

    # -- update ---------------------------------------------------------------

    def update(self, dt, keys=None):
        self.time += dt
        if keys is None:
            keys = pygame.key.get_pressed()
        if self.paused:
            return
        sdt = dt * (0.35 if self.slowmo > 0 else 1.0)
        if self.slowmo > 0:
            self.slowmo -= dt
        self.shake = max(0.0, self.shake - 30 * dt)

        vx, vy = (self.ship.vel[0], self.ship.vel[1]) \
            if self.state == "play" and self.ship.alive else (0.0, 0.0)
        for st in self.stars:
            st.update(sdt, vx, vy)

        if self.state == "menu":
            for a in self.menu_rocks:
                a.update(sdt)
            for p in self.particles:
                p.update(sdt)
            self.particles = [p for p in self.particles if p.t > 0]
            return

        if self.state == "over":
            self.over_t += dt
            for a in self.asteroids:
                a.update(sdt)
            for sa in self.saucers:
                sa.update(sdt, self.ship, self)
            for sb in self.saucer_bullets:
                sb.update(sdt)
            self.saucer_bullets = [sb for sb in self.saucer_bullets if sb.t > 0]
            for p in self.particles:
                p.update(sdt)
            for pop in self.popups:
                pop.update(sdt)
            self.particles = [p for p in self.particles if p.t > 0]
            self.popups = [p for p in self.popups if p.t > 0]
            return

        self.update_play(dt, sdt, keys)

    def update_play(self, dt, sdt, keys):
        sh = self.ship

        # --- ship ------------------------------------------------------------
        if sh.alive:
            if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                sh.angle -= 4.2 * sdt
            if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                sh.angle += 4.2 * sdt
            sh.thrusting = bool(keys[pygame.K_UP] or keys[pygame.K_w])
            if sh.thrusting:
                sh.vel[0] += math.cos(sh.angle) * 380 * sdt
                sh.vel[1] += math.sin(sh.angle) * 380 * sdt
                bx, by = sh.transform(-8, 0)
                for _ in range(2):
                    ang = sh.angle + math.pi + random.uniform(-0.4, 0.4)
                    sp = random.uniform(50, 130)
                    self.particles.append(Particle(
                        [bx, by], [math.cos(ang) * sp, math.sin(ang) * sp],
                        random.uniform(0.12, 0.3),
                        random.choice([(255, 170, 60), (255, 220, 90),
                                       (255, 120, 40)]), 2))
                self.sfx.set_thrust(True)
            else:
                self.sfx.set_thrust(False)
            sp = math.hypot(sh.vel[0], sh.vel[1])
            if sp > 430:
                k = 430 / sp
                sh.vel[0] *= k
                sh.vel[1] *= k
            f = math.exp(-0.9 * sdt)
            sh.vel[0] *= f
            sh.vel[1] *= f
            sh.pos[0] += sh.vel[0] * sdt
            sh.pos[1] += sh.vel[1] * sdt
            wrap(sh.pos, 18)
            sh.fire_cd -= sdt
            if keys[pygame.K_SPACE] and sh.fire_cd <= 0:
                self.fire()
            for attr, dur in (("invincible", None), ("shield", 10),
                              ("rapid", 8), ("spread", 8)):
                v = getattr(sh, attr)
                if v > 0:
                    setattr(sh, attr, v - sdt)
        else:
            sh.thrusting = False

        # --- respawn ----------------------------------------------------------
        if not sh.alive and self.lives > 0:
            self.respawn_t -= sdt
            if self.respawn_t <= 0:
                if self.clear_spot([WIDTH / 2, HEIGHT / 2], 110):
                    sh.pos = [WIDTH / 2, HEIGHT / 2]
                    sh.vel = [0.0, 0.0]
                    sh.angle = -math.pi / 2
                    sh.alive = True
                    sh.invincible = 3.0
                else:
                    self.respawn_t = 0.5

        # --- entities ----------------------------------------------------------
        for b in self.bullets:
            b.update(sdt)
        self.bullets = [b for b in self.bullets if b.t > 0]
        for a in self.asteroids:
            a.update(sdt)
        for pu in self.powerups:
            pu.update(sdt)
        self.powerups = [pu for pu in self.powerups if pu.t > 0]
        for p in self.particles:
            p.update(sdt)
        self.particles = [p for p in self.particles if p.t > 0]
        for pop in self.popups:
            pop.update(sdt)
        self.popups = [p for p in self.popups if p.t > 0]
        if self.wave_banner > 0:
            self.wave_banner -= sdt

        # --- bullet vs asteroid ------------------------------------------------
        for a in list(self.asteroids):
            for b in self.bullets:
                if wdist2(a.pos, b.pos) < (a.radius * 0.92) ** 2:
                    self.bullets.remove(b)
                    self.kill_asteroid(a)
                    break

        # --- flying saucer -------------------------------------------------------
        for sa in self.saucers:
            sa.update(sdt, sh, self)
        for sb in self.saucer_bullets:
            sb.update(sdt)
        self.saucer_bullets = [sb for sb in self.saucer_bullets if sb.t > 0]
        for sa in list(self.saucers):
            if sa.pos[0] < -80 or sa.pos[0] > WIDTH + 80:
                self.saucers.remove(sa)

        # --- player bullet vs saucer ---------------------------------------------
        for sa in list(self.saucers):
            for b in self.bullets:
                if wdist2(sa.pos, b.pos) < sa.radius ** 2:
                    self.bullets.remove(b)
                    self.kill_saucer(sa)
                    break

        # --- saucer bullet vs ship / asteroids ------------------------------------
        for sb in list(self.saucer_bullets):
            hit = False
            if sh.alive and sh.invincible <= 0 and wdist2(sb.pos, sh.pos) < 12 ** 2:
                if sh.shield > 0:
                    sh.shield = 0.0
                    sh.invincible = 1.2
                    self.sfx.play("shield")
                else:
                    self.ship_explode()
                hit = True
            if not hit:
                for a in self.asteroids:
                    if wdist2(sb.pos, a.pos) < (a.radius * 0.92) ** 2:
                        self.kill_asteroid(a)
                        hit = True
                        break
            if hit:
                self.saucer_bullets.remove(sb)

        # --- ship vs saucer ---------------------------------------------------------
        if sh.alive and sh.invincible <= 0:
            for sa in self.saucers:
                if wdist2(sh.pos, sa.pos) < (sa.radius + 10) ** 2:
                    if sh.shield > 0:
                        sh.shield = 0.0
                        sh.invincible = 1.2
                        self.sfx.play("shield")
                        self.kill_saucer(sa)
                    else:
                        self.ship_explode()
                    break

        # --- ship vs asteroid ---------------------------------------------------
        if sh.alive and sh.invincible <= 0:
            for a in self.asteroids:
                if wdist2(sh.pos, a.pos) < (a.radius + 10) ** 2:
                    if sh.shield > 0:
                        sh.shield = 0.0
                        sh.invincible = 1.2
                        self.sfx.play("shield")
                        self.kill_asteroid(a)
                    else:
                        self.ship_explode()
                    break

        # --- power-up pickup -----------------------------------------------------
        if sh.alive:
            for pu in list(self.powerups):
                if wdist2(sh.pos, pu.pos) < 24 ** 2:
                    self.collect(pu)

        # --- saucer spawner --------------------------------------------------------
        if self.wave >= 2:
            self.saucer_timer -= sdt
            if self.saucer_timer <= 0:
                if len(self.saucers) < 2:
                    self.saucers.append(Saucer())
                    self.saucer_timer = random.uniform(12, 22)
                else:
                    self.saucer_timer = 3.0

        # --- wave management -----------------------------------------------------
        if not self.asteroids:
            if self.wave_delay is None:
                self.wave_delay = 1.6
                if self.wave > 0:
                    bonus = 250 * self.wave
                    self.add_score(bonus)
                    self.popups.append(Popup(
                        [WIDTH / 2, HEIGHT / 2 - 40],
                        "WAVE CLEARED  +{}".format(bonus), (120, 255, 170)))
            else:
                self.wave_delay -= sdt
                if self.wave_delay <= 0:
                    self.next_wave()

    # -- draw ---------------------------------------------------------------------

    def draw_world(self, s, rocks):
        s.fill((6, 6, 14))
        for st in self.stars:
            st.draw(s, self.time)
        for p in self.particles:
            p.draw(s)
        for pu in self.powerups:
            pu.draw(s, self.f_tiny)
        for b in self.bullets:
            b.draw(s)
        for sb in self.saucer_bullets:
            sb.draw(s)
        for a in rocks:
            a.draw(s)
        if self.state in ("play", "over"):
            for sa in self.saucers:
                sa.draw(s)
        if self.state in ("play", "over"):
            self.ship.draw(s)
        for pop in self.popups:
            pop.draw(s, self.f_sm)

    def center_text(self, s, text, font, color, pos, glow=None):
        t = font.render(text, True, color)
        r = t.get_rect(center=pos)
        if glow:
            g = font.render(text, True, glow)
            s.blit(g, (r.x - 1, r.y), (r.x + 1, r.y), (r.x, r.y + 1), (r.x - 1, r.y + 1))
        s.blit(t, r)
        return r

    def draw_hud(self):
        s = self.screen
        s.blit(self.f_sm.render("SCORE {:07d}".format(self.score), True,
                                (230, 235, 245)), (14, 10))
        hi = self.f_sm.render("HIGH {:07d}".format(max(self.highscore, self.score)),
                              True, (255, 220, 120))
        s.blit(hi, (WIDTH - 14 - hi.get_width(), 10))
        if self.state == "play":
            self.center_text(s, "WAVE {}".format(self.wave), self.f_sm,
                             (140, 200, 255), (WIDTH // 2, 20))
            for i in range(max(0, self.lives)):
                x, y = 22 + i * 24, HEIGHT - 20
                pygame.draw.polygon(s, (230, 235, 245),
                                    [(x, y - 9), (x - 8, y + 7), (x + 8, y + 7)], 2)
            for i in range(self.bombs):
                x, y = WIDTH - 24 - i * 28, HEIGHT - 20
                pygame.draw.circle(s, (255, 90, 130), (x, y), 9, 2)
                t = self.f_tiny.render("B", True, (255, 90, 130))
                s.blit(t, t.get_rect(center=(x, y)))
            items = []
            if self.ship.rapid > 0:
                items.append(("RAPID", self.ship.rapid / 8.0, KIND_COLORS["RAPID"]))
            if self.ship.spread > 0:
                items.append(("SPREAD", self.ship.spread / 8.0, KIND_COLORS["SPREAD"]))
            if self.ship.shield > 0:
                items.append(("SHIELD", self.ship.shield / 10.0, KIND_COLORS["SHIELD"]))
            y = HEIGHT - 18
            for name, frac, col in items:
                t = self.f_tiny.render(name, True, col)
                s.blit(t, (WIDTH // 2 - 130, y - 8))
                pygame.draw.rect(s, (40, 44, 60),
                                 (WIDTH // 2 - 60, y - 7, 60, 6))
                pygame.draw.rect(s, col,
                                 (WIDTH // 2 - 60, y - 7, int(60 * frac), 6))
                y -= 18

    def draw(self):
        s = self.screen
        ox = oy = 0
        if self.shake > 0.3:
            ox = random.uniform(-self.shake, self.shake)
            oy = random.uniform(-self.shake, self.shake)
        s.fill((0, 0, 0))
        self.draw_world(self.world, self.menu_rocks if self.state == "menu"
                        else self.asteroids)
        s.blit(self.world, (ox, oy))

        if self.state == "menu":
            self.center_text(s, "A S T E R O I D S", self.f_huge,
                             (235, 240, 250), (WIDTH // 2, HEIGHT // 2 - 130))
            self.center_text(s, "A  PYGAME  ARCADE  CLASSIC", self.f_med,
                             (120, 150, 210), (WIDTH // 2, HEIGHT // 2 - 75))
            self.center_text(s, "HIGH SCORE  {:07d}".format(self.highscore),
                             self.f_sm, (255, 220, 120),
                             (WIDTH // 2, HEIGHT // 2 - 35))
            pulse = 0.6 + 0.4 * math.sin(self.time * 4)
            c = (int(150 + 105 * pulse), int(220 * pulse + 35), 255)
            self.center_text(s, "PRESS  ENTER  TO  START", self.f_med, c,
                             (WIDTH // 2, HEIGHT // 2 + 20))
            lines = ["LEFT/RIGHT  ROTATE      UP  THRUST      SPACE  FIRE",
                     "B  BOMB                P  PAUSE         F11  FULLSCREEN",
                     "FROM WAVE 2: FLYING SAUCERS   150 / 300 PTS"]
            for i, ln in enumerate(lines):
                self.center_text(s, ln, self.f_sm, (150, 165, 200),
                                 (WIDTH // 2, HEIGHT // 2 + 80 + i * 26))
            x0 = WIDTH // 2 - 190
            for i, kind in enumerate(KIND_COLORS):
                c = KIND_COLORS[kind]
                x = x0 + i * 100
                y = HEIGHT // 2 + 165
                pygame.draw.polygon(s, c, [(x, y - 8), (x + 8, y), (x, y + 8), (x - 8, y)], 1)
                t = self.f_tiny.render(kind, True, c)
                s.blit(t, (x + 14, y - 8))
            self.center_text(s, "ESC  QUIT", self.f_tiny, (90, 100, 130),
                             (WIDTH - 50, HEIGHT - 16))
            sc = (110, 255, 160) if self.sfx.ok else (255, 110, 110)
            self.center_text(s, "SOUND  " + ("ON" if self.sfx.ok else "OFF"),
                             self.f_tiny, sc, (50, HEIGHT - 16))

        elif self.state == "play":
            self.draw_hud()
            if self.wave_banner > 0:
                k = min(self.wave_banner, 1.0)
                c = (int(100 * k + 60), int(200 * k + 55), 255)
                self.center_text(s, "WAVE {}".format(self.wave), self.f_med, c,
                                 (WIDTH // 2, HEIGHT // 2 - 60))
            if self.paused:
                ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                ov.fill((0, 0, 20, 170))
                s.blit(ov, (0, 0))
                self.center_text(s, "PAUSED", self.f_huge, (230, 235, 245),
                                 (WIDTH // 2, HEIGHT // 2 - 20))
                self.center_text(s, "P  RESUME      ESC  MENU", self.f_sm,
                                 (170, 180, 210), (WIDTH // 2, HEIGHT // 2 + 40))

        else:  # game over
            self.draw_hud()
            self.center_text(s, "GAME OVER", self.f_huge, (255, 80, 90),
                             (WIDTH // 2, HEIGHT // 2 - 110))
            self.center_text(s, "SCORE  {:07d}".format(self.score), self.f_med,
                             (230, 235, 245), (WIDTH // 2, HEIGHT // 2 - 45))
            self.center_text(s, "WAVES SURVIVED  {}".format(self.wave), self.f_sm,
                             (170, 180, 210), (WIDTH // 2, HEIGHT // 2 - 10))
            self.center_text(s, "HIGH SCORE  {:07d}".format(self.highscore),
                             self.f_sm, (255, 220, 120),
                             (WIDTH // 2, HEIGHT // 2 + 20))
            if self.new_record and int(self.over_t * 2.5) % 2 == 0:
                self.center_text(s, "* NEW HIGH SCORE *", self.f_med,
                                 (120, 255, 170), (WIDTH // 2, HEIGHT // 2 + 65))
            if self.over_t > 0.8:
                self.center_text(s, "ENTER  PLAY AGAIN      ESC  MENU",
                                 self.f_sm, (170, 180, 210),
                                 (WIDTH // 2, HEIGHT // 2 + 120))


# ----------------------------------------------------------------- input --

class FakeKeys:
    """Key-state stub used by the headless self-test."""

    def __init__(self):
        self.held = set()

    def __getitem__(self, k):
        return k in self.held


def wrapped_aim(from_p, to_p):
    dx = to_p[0] - from_p[0]
    if dx > WIDTH / 2:
        dx -= WIDTH
    elif dx < -WIDTH / 2:
        dx += WIDTH
    dy = to_p[1] - from_p[1]
    if dy > HEIGHT / 2:
        dy -= HEIGHT
    elif dy < -HEIGHT / 2:
        dy += HEIGHT
    return math.atan2(dy, dx)


def simulate(game, frame):
    """Drive the game automatically for the headless self-test."""
    keys = FakeKeys()
    if frame == 30:
        game.start_game()
    if frame == 150:
        game.nuke()
    if frame == 250:
        game.paused = True
    if frame == 270:
        game.paused = False
    if frame == 200:
        for kind in KIND_COLORS:
            p = [game.ship.pos[0] + 6, game.ship.pos[1] + 6]
            game.powerups.append(PowerUp(p, kind))
    if frame == 300 and game.state == "play":
        game.saucers.append(Saucer())
    if frame % 45 < 16 and game.state == "play" and game.ship.alive \
            and not game.paused:
        keys.held.add(pygame.K_SPACE)
        best, bd = None, float("inf")
        for a in game.asteroids:
            d = wdist2(game.ship.pos, a.pos)
            if d < bd:
                bd, best = d, a
        if best is not None:
            game.ship.angle = wrapped_aim(game.ship.pos, best.pos)
    if frame == 400 and game.state == "play" and game.ship.alive:
        sh = game.ship
        sh.invincible = 0.0
        sh.shield = 0.0
        game.asteroids.append(Asteroid([sh.pos[0] + 1, sh.pos[1] + 1], [0, 0], 2))
    if game.state == "play":
        game.lives = max(game.lives, 4)
    if frame == 520:
        game.start_game()
    return keys


# ------------------------------------------------------------------ main --

def main():
    sfx = SFX()
    pygame.init()
    sfx.build()
    if not sfx.ok:
        print("WARNING: no sound - could not initialise the audio device.")
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("ASTEROIDS")
    clock = pygame.time.Clock()
    game = Game(screen, sfx)
    fullscreen = False
    frame = 0
    running = True
    while running:
        dt = min(clock.tick(FPS) / 1000.0, 1 / 20)
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_F11:
                    fullscreen = not fullscreen
                    screen = pygame.display.set_mode(
                        (WIDTH, HEIGHT), pygame.FULLSCREEN if fullscreen else 0)
                    game.screen = screen
                elif game.state == "menu":
                    if e.key == pygame.K_RETURN:
                        game.start_game()
                    elif e.key == pygame.K_ESCAPE:
                        running = False
                elif game.state == "play":
                    if e.key == pygame.K_p:
                        game.paused = not game.paused
                    elif e.key == pygame.K_ESCAPE:
                        game.to_menu()
                    elif e.key in (pygame.K_b, pygame.K_x):
                        game.nuke()
                elif game.state == "over" and game.over_t > 0.8:
                    if e.key == pygame.K_RETURN:
                        game.start_game()
                    elif e.key == pygame.K_ESCAPE:
                        game.to_menu()
        if SELFTEST:
            keys = simulate(game, frame)
        else:
            keys = None
        game.update(dt, keys)
        game.draw()
        pygame.display.flip()
        frame += 1
        if SELFTEST and frame >= SELFTEST_FRAMES:
            print("self-test OK: score={} wave={} asteroids={} particles={} "
                  "state={} sound={}".format(
                      game.score, game.wave, len(game.asteroids),
                      len(game.particles), game.state, sfx.ok))
            running = False
    save_highscore(game.highscore)
    pygame.quit()


if __name__ == "__main__":
    main()