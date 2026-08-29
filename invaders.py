"""
COSMIC INVADERS -- a modern reimagining of Space Invaders in pure Python + pygame.

All art AND all sound are generated in code. No asset files, no downloads.

Run:        python space_invaders.py
Self-test:  python space_invaders.py --selftest

Controls:
    Arrow keys / A D   move
    SPACE (hold ok)    fire
    P or ESC           pause
    SPACE / ESC        restart / menu (on game over)

Features: classic 55-creature grid with accelerating march, destructible bunkers,
bonus UFO, power-ups (rapid fire, spread shot, shield, slow-time, extra life),
particle explosions, screen shake, floating score text, parallax starfield,
synthesized retro sound effects, persistent hi-score, CRT scanline filter.
"""
import math
import os
import random
from array import array
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

try:
    import pygame
except ImportError:
    sys.exit("This game needs pygame. Install it with:  pip install pygame\n")

# ---------------------------------------------------------------- constants
W, H = 900, 660
FPS = 60
RATE = 44100
GROUND_Y = H - 46
PLAYER_Y = GROUND_Y - 30
SHIELD_Y = H - 168
UFO_Y = 54
SCALE = 3
COL_SPACING = 56
CS = 5  # shield cell size
HI_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "invaders_highscore.txt")

INV_COLORS = {"OCTO": (255, 90, 215), "CRAB": (95, 220, 255), "SQUID": (165, 255, 130)}
POWER_COLORS = {"rapid": (255, 220, 80), "spread": (140, 220, 255),
                "shield": (120, 255, 140), "slow": (255, 160, 255),
                "life": (255, 90, 120)}

# ------------------------------------------------------------- pixel artwork
ART = {
    "OCTO": (
        ["....####....", ".##########.", "############", "###..##..###",
         "############", "...##..##...", "..##.##.##..", "##........##"],
        ["....####....", ".##########.", "############", "###..##..###",
         "############", "..###..###..", ".##..##..##.", "..##....##.."],
    ),
    "CRAB": (
        ["..#.....#..", "...#...#...", "..#######..", ".##.###.##.",
         "###########", "#.#######.#", "#.#.....#.#", "...##.##..."],
        ["..#.....#..", "#..#...#..#", "#.#######.#", "###.###.###",
         "###########", ".#########.", "..#.....#..", ".#.......#."],
    ),
    "SQUID": (
        ["...##...", "..####..", ".######.", "##.##.##",
         "########", ".#.##.#.", ".#.##.#.", "..#..#.."],
        ["...##...", "..####..", ".######.", "##.##.##",
         "########", "..#..#..", ".#....#.", "#.#..#.#"],
    ),
    "PLAYER": (
        ["......#......", ".....###.....", ".....###.....", ".###########.",
         "#############", "#############", "#############", "#############"],
    ),
    "UFO": (
        [".....######.....", "...##########...", "..############..",
         ".##.##.##.##.##.", "################", "...###....###...", "....#......#...."],
    ),
}
SHIELD_ART = (
    "....########....", "...##########...", "..############..", ".##############.",
    "################", "################", "################", "################",
    "################", "#######..#######", "######....######", "######....######",
    "####........####", "####........####", "####........####", "####........####",
)

SPRITES = {}
GLOW = {}


def _sprite(rows, color, scale=SCALE):
    w = max(len(r) for r in rows) * scale
    h = len(rows) * scale
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "#":
                surf.fill(color, (x * scale, y * scale, scale, scale))
    return surf


def _glow(rows, color, scale=SCALE):
    base = _sprite(rows, color, scale)
    g = pygame.transform.smoothscale(
        base, (max(2, int(base.get_width() * 1.7)), max(2, int(base.get_height() * 1.7))))
    g.set_alpha(44)
    return g


def build_assets():
    global SPRITES, GLOW
    for kind in ("OCTO", "CRAB", "SQUID"):
        SPRITES[kind] = [_sprite(f, INV_COLORS[kind]) for f in ART[kind]]
        GLOW[kind] = [_glow(ART[kind][0], INV_COLORS[kind]) for _ in ART[kind]]
    SPRITES["PLAYER"] = [_sprite(ART["PLAYER"][0], (125, 255, 235))]
    GLOW["PLAYER"] = [_glow(ART["PLAYER"][0], (125, 255, 235))]
    SPRITES["UFO"] = [_sprite(ART["UFO"][0], (255, 90, 90))]
    GLOW["UFO"] = [_glow(ART["UFO"][0], (255, 90, 90))]


# --------------------------------------------------- synthesized sound effects
def _sweep(f0, f1, dur, wave="sq", vol=0.5):
    n = int(RATE * dur)
    ph = 0.0
    out = []
    for i in range(n):
        t = i / RATE
        f = f0 + (f1 - f0) * (i / max(1, n - 1))
        ph += 2.0 * math.pi * f / RATE
        v = (1.0 if math.sin(ph) >= 0 else -1.0) if wave == "sq" else math.sin(ph)
        env = min(1.0, (dur - t) / max(dur * 0.45, 1e-6), t / 0.004 + 0.001)
        out.append(v * vol * env)
    return out


def _noise(dur, vol=0.5, decay=2.0):
    n = int(RATE * dur)
    return [random.uniform(-1, 1) * vol * ((1 - i / n) ** decay) for i in range(n)]


def _mix(*lists):
    n = max(len(x) for x in lists)
    out = [0.0] * n
    for x in lists:
        for i, v in enumerate(x):
            out[i] += v
    return out


def _notes(freqs, dur, vol):
    out = []
    for f in freqs:
        out += _sweep(f, f * 0.98, dur, "sq", vol)
    return out


def _warble(dur, vol):
    n = int(RATE * dur)
    ph = 0.0
    out = []
    for i in range(n):
        t = i / RATE
        f = 640.0 + 240.0 * math.sin(2.0 * math.pi * 2.4 * t)
        ph += 2.0 * math.pi * f / RATE
        env = min(1.0, (dur - t) / (dur * 0.5), t / 0.01)
        out.append(math.sin(ph) * vol * env)
    return out


class Sfx:
    """Every sound is synthesized at startup from raw waveforms using only
    the Python standard library (math + array) -- no asset files and no
    third-party audio libraries.  Buffers are built to exactly match the
    format the sound device actually opened with, so playback works
    regardless of what the OS audio driver decided to use."""

    def __init__(self):
        self.sounds = {}
        self.ok = False
        spec = pygame.mixer.get_init()
        if not spec:
            return
        try:
            self.freq, self.size, self.channels = spec[0], spec[1], spec[2]
            self._build()
            self.ok = True
        except Exception:
            self.ok = False

    def _resample(self, samples, target):
        out = []
        n = int(len(samples) * target / RATE)
        step = RATE / float(target)
        last = len(samples) - 1
        for i in range(n):
            pos = i * step
            i0 = int(pos)
            i1 = min(i0 + 1, last)
            frac = pos - i0
            out.append(samples[i0] * (1.0 - frac) + samples[i1] * frac)
        return out

    def _mk(self, samples):
        if self.freq != RATE:
            samples = self._resample(samples, self.freq)
        if self.size == -16:            # signed 16-bit
            buf = array("h", (int(max(-1.0, min(1.0, s)) * 30000) for s in samples))
        elif self.size == 16:           # unsigned 16-bit
            buf = array("H", (int((max(-1.0, min(1.0, s)) + 1.0) * 32767.5)
                             for s in samples))  # -1..1 -> 0..65535, full range
        elif self.size == -8:           # signed 8-bit
            buf = array("b", (int(max(-1.0, min(1.0, s)) * 120) for s in samples))
        else:                           # unsigned 8-bit
            buf = array("B", (int((max(-1.0, min(1.0, s)) + 1.0) * 127.5)
                              for s in samples))  # -1..1 -> 0..255, full range
        if self.channels > 1:           # duplicate mono into each channel
            buf = array(buf.typecode, (buf[i] for i in range(len(buf))
                                       for _ in range(self.channels)))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _build(self):
        s = self.sounds
        s["shoot"] = self._mk(_sweep(1150, 160, 0.09, "sq", 0.20))
        s["laser"] = self._mk(_sweep(340, 100, 0.13, "sq", 0.12))
        s["boom"] = self._mk(_mix(_noise(0.32, 0.5, 2.4), _sweep(230, 40, 0.28, "sq", 0.18)))
        s["bigboom"] = self._mk(_mix(_noise(0.85, 0.6, 1.7), _sweep(300, 26, 0.80, "sq", 0.28)))
        s["ufo"] = self._mk(_warble(0.42, 0.10))
        s["power"] = self._mk(_notes((523.0, 659.0, 784.0, 1046.0), 0.06, 0.22))
        s["oneup"] = self._mk(_notes((392.0, 523.0, 659.0, 784.0, 1046.0, 1318.0), 0.055, 0.22))
        s["scrape"] = self._mk(_sweep(310, 140, 0.08, "sq", 0.12))
        for i, f in enumerate((146.83, 123.47, 98.00, 82.41)):
            s["step%d" % i] = self._mk(_sweep(f, f * 0.90, 0.075, "sq", 0.30))

    def play(self, name, vol=1.0):
        if not self.ok:
            return
        snd = self.sounds.get(name)
        if snd:
            snd.set_volume(vol)
            snd.play()

# ------------------------------------------------------------------- game
class Game:
    def __init__(self, selftest=False):
        self.selftest = selftest
        self.sfx = Sfx()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("COSMIC INVADERS")
        try:
            pygame.display.set_icon(SPRITES["PLAYER"][0])
        except Exception:
            pass
        self.board = pygame.Surface((W, H))
        self.font = pygame.font.Font(None, 30)
        self.font_big = pygame.font.Font(None, 84)
        self.font_small = pygame.font.Font(None, 22)

        # CRT scanlines + background gradient
        self.scan = pygame.Surface((W, H), pygame.SRCALPHA)
        for y in range(0, H, 3):
            self.scan.fill((0, 0, 0, 26), (0, y, W, 1))
        self.bg = pygame.Surface((W, H))
        for y in range(H):
            k = y / H
            pygame.draw.line(self.bg, (int(6 + 10 * k), int(8 + 14 * k), int(18 + 26 * k)),
                             (0, y), (W, y))
        self.life_icon = pygame.transform.scale(SPRITES["PLAYER"][0], (26, 16))

        self.power_sprites = {}
        for kind, letter in (("rapid", "R"), ("spread", "S"), ("shield", "O"),
                             ("slow", "T"), ("life", "+")):
            col = POWER_COLORS[kind]
            s = pygame.Surface((30, 30), pygame.SRCALPHA)
            pygame.draw.rect(s, (8, 14, 28), (1, 1, 28, 28), border_radius=7)
            pygame.draw.rect(s, col, (1, 1, 28, 28), 2, border_radius=7)
            img = self.font_small.render(letter, True, col)
            s.blit(img, img.get_rect(center=(15, 15)))
            self.power_sprites[kind] = s

        self.load_hi()
        self.score = 0
        self.level = 1
        self.new_record = False
        self.t = 0.0
        self.shake = 0.0
        self.state = "menu"
        self.wave_timer = 0.0
        self.over_at = 0.0
        self.test_t = 0.0
        self.make_stars()
        self.particles = []
        self.popups = []
        self.player = self._fresh_player()
        self.bullets = []
        self.powerups = []
        self.invaders = []
        self.bunkers = []
        self.ufo = None
        self.ufo_timer = 10.0
        self.gnaw_at = 0.0

    @staticmethod
    def _fresh_player():
        return {"x": W // 2, "lives": 3, "cool": 0.0, "inv": 0.0, "shield": False,
                "rapid_until": 0.0, "spread_until": 0.0, "slow_until": 0.0,
                "rapid": False, "spread": False}

    # ------------------------------------------------------------- hi-score
    def load_hi(self):
        try:
            with open(HI_FILE) as f:
                self.hi = int(f.read().strip() or 0)
        except Exception:
            self.hi = 0

    def save_hi(self):
        try:
            with open(HI_FILE, "w") as f:
                f.write(str(self.hi))
        except Exception:
            pass

    # ----------------------------------------------------------- state flow
    def start_game(self):
        self.score = 0
        self.level = 1
        self.new_record = False
        self.player = self._fresh_player()
        self.state = "wave"
        self.wave_timer = 1.4
        self.new_wave()
        self.sfx.play("power")

    def new_wave(self):
        self.invaders = []
        c0 = W // 2 - 5 * COL_SPACING
        for row, kind in enumerate(("OCTO", "CRAB", "CRAB", "SQUID", "SQUID")):
            w = SPRITES[kind][0].get_width()
            for c in range(11):
                r = pygame.Rect(0, 0, w, 24)
                r.centerx = c0 + c * COL_SPACING
                r.top = 92 + row * 40
                self.invaders.append({"alive": True, "kind": kind, "rect": r})
        self.dir = 1
        self.frame_idx = 0
        self.step_idx = 0
        self.step_timer = 0.0
        self.anim_timer = 0.0
        self.shoot_timer = 1.0
        self.bullets = []
        self.powerups = []
        self.ufo = None
        self.ufo_timer = random.uniform(10, 18)
        self.build_shields()

    def build_shields(self):
        self.bunkers = []
        bw, bh = len(SHIELD_ART[0]) * CS, len(SHIELD_ART) * CS
        for cx in (W // 2 - 215, W // 2 - 72, W // 2 + 72, W // 2 + 215):
            grid = [[1 if ch == "#" else 0 for ch in row] for row in SHIELD_ART]
            self.bunkers.append({"grid": grid, "rect": pygame.Rect(cx - bw // 2, SHIELD_Y, bw, bh)})

    # --------------------------------------------------------------- events
    def handle_events(self, e):
        if e.type != pygame.KEYDOWN:
            return
        k = e.key
        if self.state == "menu":
            if k in (pygame.K_SPACE, pygame.K_RETURN):
                self.start_game()
            elif k == pygame.K_ESCAPE:
                pygame.event.post(pygame.event.Event(pygame.QUIT))
        elif self.state == "play":
            if k in (pygame.K_p, pygame.K_ESCAPE):
                self.state = "pause"
        elif self.state == "pause":
            if k in (pygame.K_p, pygame.K_ESCAPE, pygame.K_SPACE):
                self.state = "play"
        elif self.state == "over":
            # Restart requires a deliberate press: ignore the frantic
            # space-bar mashing (and key auto-repeat) for a short lockout
            # right after death, so dying mid-frenzy doesn't instantly
            # launch a new game.
            if k in (pygame.K_SPACE, pygame.K_RETURN):
                if self.t > self.over_at + 1.0 and not e.keyrepeat:
                    self.start_game()
            elif k == pygame.K_ESCAPE:
                self.state = "menu"

    # -------------------------------------------------------------- update
    def update(self, dt):
        self.t += dt
        self.shake *= 0.88
        if self.shake < 0.3:
            self.shake = 0.0
        self.update_stars(dt)
        self.update_particles(dt)
        self.update_popups(dt)
        if self.state == "wave":
            self.wave_timer -= dt
            if self.wave_timer <= 0:
                self.state = "play"
        elif self.state == "play":
            self.update_player(dt)
            self.update_bullets(dt)
            self.update_invaders(dt)
            self.update_ufo(dt)
            self.update_powerups(dt)
        if self.selftest:
            self.update_selftest(dt)

    def update_selftest(self, dt):
        if self.state == "menu" and self.t > 0.5:
            self.start_game()
        p = self.player
        if self.state in ("play", "wave"):
            p["x"] = W // 2 + int(math.sin(self.t * 1.7) * 220)
        self.test_t -= dt
        if self.test_t <= 0:
            self.test_t = 0.3
            if self.state == "play":
                self.fire()
                alive = [i for i in self.invaders if i["alive"]]
                if alive and random.random() < 0.6:
                    self.kill_invader(random.choice(alive))
                if random.random() < 0.3:
                    self.drop_powerup(p["x"], 220)
        if self.state == "over" and self.t > self.over_at + 2.5:
            self.start_game()

    def make_stars(self):
        self.stars = []
        for _ in range(130):
            d = random.random()
            self.stars.append({
                "x": random.randint(0, W - 2), "y": random.randint(0, H - 2),
                "size": 1 if d < 0.6 else 2, "speed": 12 + d * d * 60,
                "color": (90 + int(d * 80), 90 + int(d * 90), 120 + int(d * 100)),
            })

    def update_stars(self, dt):
        for st in self.stars:
            st["y"] += st["speed"] * dt
            if st["y"] >= H:
                st["y"] -= H
                st["x"] = random.randint(0, W - 2)

    def update_particles(self, dt):
        keep = []
        for p in self.particles:
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vx"] *= 0.985
            p["vy"] *= 0.985
            p["life"] -= dt
            if p["life"] > 0:
                keep.append(p)
        self.particles = keep

    def update_popups(self, dt):
        keep = []
        for p in self.popups:
            p["y"] -= 26 * dt
            p["life"] -= dt * 1.2
            if p["life"] > 0:
                keep.append(p)
        self.popups = keep

    def explosion(self, x, y, color, n, speed):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            sp = random.uniform(speed * 0.25, speed)
            self.particles.append({
                "x": x, "y": y, "vx": math.cos(a) * sp, "vy": math.sin(a) * sp,
                "life": random.uniform(0.3, 0.7), "max": 0.7,
                "color": color, "size": random.randint(2, 4),
            })

    def popup(self, text, x, y, color, small=False):
        self.popups.append({"text": text, "x": x, "y": y, "color": color,
                            "life": 1.0, "font": self.font_small if small else self.font})

    # --------------------------------------------------------------- player
    def update_player(self, dt):
        p = self.player
        p["rapid"] = self.t < p["rapid_until"]
        p["spread"] = self.t < p["spread_until"]
        keys = pygame.key.get_pressed()
        v = 0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            v -= 1
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            v += 1
        p["x"] = max(30, min(W - 30, p["x"] + v * 340 * dt))
        p["cool"] -= dt
        if (keys[pygame.K_SPACE] or keys[pygame.K_j]) and p["cool"] <= 0:
            p["cool"] = 0.15 if p["rapid"] else 0.40
            self.fire()

    def fire(self):
        p = self.player
        if not p["rapid"] and any(b["up"] for b in self.bullets):
            return
        if p["spread"]:
            shots = [(-110, -540), (0, -570), (110, -540)]
        else:
            shots = [(0, -560)]
        for vx, vy in shots:
            self.bullets.append({"up": True, "x": float(p["x"]), "y": float(PLAYER_Y - 6),
                                 "vx": vx, "vy": vy,
                                 "rect": pygame.Rect(p["x"] - 2, PLAYER_Y - 18, 4, 14)})
        for _ in range(4):
            self.particles.append({"x": p["x"] + random.uniform(-4, 4), "y": float(PLAYER_Y - 4),
                                   "vx": random.uniform(-40, 40), "vy": random.uniform(-120, -40),
                                   "life": 0.12, "max": 0.12, "color": (255, 255, 180), "size": 2})
        self.sfx.play("shoot")

    def hit_player(self):
        p = self.player
        if p["shield"]:
            p["shield"] = False
            self.explosion(p["x"], PLAYER_Y + 10, (110, 255, 160), 18, 200)
            self.popup("SHIELD DOWN", p["x"], PLAYER_Y - 16, (110, 255, 160), small=True)
            self.sfx.play("power")
            p["inv"] = self.t + 1.0
            return
        p["lives"] -= 1
        self.explosion(p["x"], PLAYER_Y + 10, (130, 255, 240), 30, 240)
        self.explosion(p["x"], PLAYER_Y + 10, (255, 140, 60), 20, 160)
        self.shake = 14
        self.sfx.play("bigboom")
        if p["lives"] <= 0:
            self.game_over()
        else:
            p["inv"] = self.t + 2.2

    def game_over(self):
        self.over_at = self.t
        if self.score > self.hi:
            self.hi = self.score
            self.new_record = True
            self.save_hi()
        self.state = "over"

    # -------------------------------------------------------------- bullets
    def update_bullets(self, dt):
        keep = []
        p = self.player
        for b in self.bullets:
            b["x"] += b["vx"] * dt
            b["y"] += b["vy"] * dt
            b["rect"].center = (int(b["x"]), int(b["y"]))
            dead = False
            if b["y"] < 30 or b["y"] > H + 20 or b["x"] < -20 or b["x"] > W + 20:
                dead = True
            elif b["up"]:
                if self.ufo is not None and b["rect"].colliderect(self.ufo["rect"]):
                    self.kill_ufo(b["rect"])
                    dead = True
                else:
                    for inv in self.invaders:
                        if inv["alive"] and b["rect"].colliderect(inv["rect"].inflate(-8, -8)):
                            self.kill_invader(inv)
                            dead = True
                            break
                    if not dead and self._hit_shield(b["rect"].centerx, b["rect"].centery, 8):
                        dead = True
            else:
                if self._hit_shield(b["rect"].centerx, b["rect"].centery, 7):
                    dead = True
                elif self.state == "play" and self.t >= p["inv"]:
                    pr = pygame.Rect(p["x"] - 16, PLAYER_Y + 2, 32, 20)
                    if b["rect"].colliderect(pr):
                        self.hit_player()
                        dead = True
            if not dead:
                keep.append(b)
        self.bullets = keep

    # --------------------------------------------------------------- shields
    def _hit_shield(self, x, y, radius):
        hit = False
        r2 = (radius + 2) ** 2
        for b in self.bunkers:
            br = b["rect"]
            if not br.collidepoint(x, y) and abs(x - br.centerx) > br.w / 2 + radius \
                    and abs(y - br.centery) > br.h / 2 + radius:
                continue
            g = b["grid"]
            x0 = max(0, int((x - br.x - radius - 2) // CS))
            x1 = min(len(g[0]), int((x - br.x + radius + 2) // CS) + 1)
            y0 = max(0, int((y - br.y - radius - 2) // CS))
            y1 = min(len(g), int((y - br.y + radius + 2) // CS) + 1)
            for gy in range(y0, y1):
                for gx in range(x0, x1):
                    cx = br.x + (gx + 0.5) * CS
                    cy = br.y + (gy + 0.5) * CS
                    if (cx - x) ** 2 + (cy - y) ** 2 <= r2 and g[gy][gx]:
                        g[gy][gx] = 0
                        hit = True
        return hit

    def invaders_vs_shields(self):
        """Zero out every bunker cell an invader rect covers.
        Returns the (x, y) centre of each cell destroyed this pass."""
        erased = []
        for inv in self.invaders:
            if not inv["alive"]:
                continue
            r = inv["rect"]
            for b in self.bunkers:
                br = b["rect"]
                if not r.colliderect(br):
                    continue
                g = b["grid"]
                for gy in range(len(g)):
                    cy = br.y + gy * CS
                    if not (r.top <= cy + CS - 1 and cy <= r.bottom - 1):
                        continue
                    row = g[gy]
                    for gx in range(len(row)):
                        if not row[gx]:
                            continue
                        cx = br.x + gx * CS
                        if r.left <= cx + CS - 1 and cx <= r.right - 1:
                            row[gx] = 0
                            erased.append((cx + CS // 2, cy + CS // 2))
        return erased

    def gnaw_shields(self):
        """Invaders chewing through a bunker: erode every covered cell, kick up
        green debris and a low scrape for each pass that destroyed something."""
        erased = self.invaders_vs_shields()
        if not erased:
            return
        for x, y in erased[:40]:
            self.explosion(x, y, (120, 235, 150), 2, 70)
        if self.t - self.gnaw_at > 0.12:
            self.gnaw_at = self.t
            self.sfx.play("scrape", 0.8)

    # ------------------------------------------------------------- invaders
    @staticmethod
    def _step_interval(speed):
        """Footstep tempo is locked to the actual marching speed: as the
        creatures stride faster (fewer alive, higher wave, slow power-up
        lifted) the background steps clatter proportionally faster."""
        return min(0.75, max(0.08, 0.75 * 55.0 / speed))

    def update_invaders(self, dt):
        # animation: flip frames on a timer (only advances while in play)
        self.anim_timer += dt
        self.frame_idx = int(self.anim_timer / 0.28) % 2

        alive = sum(1 for i in self.invaders if i["alive"])
        total = len(self.invaders) or 1
        if alive == 0:
            return
        ratio = alive / total
        speed = (55 + 150 * (1 - ratio)) * (1 + 0.12 * (self.level - 1))
        slow = 0.45 if self.t < self.player["slow_until"] else 1.0
        speed *= slow
        moved = False
        for inv in self.invaders:
            if inv["alive"]:
                inv["rect"].x += self.dir * speed * dt
                moved = True
        if moved:
            margin = 10
            hit_edge = any(i["rect"].left < margin or i["rect"].right > W - margin
                           for i in self.invaders if i["alive"])
            if hit_edge:
                self.dir *= -1
                for inv in self.invaders:
                    if inv["alive"]:
                        inv["rect"].y += 24
                        inv["rect"].x += self.dir * speed * dt
                self.step_timer = 0.0
        self.step_timer += dt
        interval = self._step_interval(speed)
        if self.step_timer >= interval:
            self.step_timer = 0.0
            self.sfx.play("step%d" % self.step_idx)
            self.step_idx = (self.step_idx + 1) % 4

        self.shoot_timer -= dt
        max_b = min(8, 3 + self.level)
        enemy = sum(1 for b in self.bullets if not b["up"])
        if self.shoot_timer <= 0 and enemy < max_b:
            self.shoot_timer = max(0.2, (0.85 - 0.05 * self.level) * (0.35 + 0.65 * ratio))
            self.invader_fire()

        lowest = 0
        for inv in self.invaders:
            if inv["alive"]:
                lowest = max(lowest, inv["rect"].bottom)
        # erode the bunkers every frame the grid overlaps them -- not only on
        # the step-down -- so creatures never stride across intact shields
        if lowest > SHIELD_Y:
            self.gnaw_shields()
        if lowest >= PLAYER_Y - 8:
            self.player["lives"] = 0
            self.explosion(self.player["x"], PLAYER_Y + 10, (130, 255, 240), 30, 240)
            self.shake = 16
            self.sfx.play("bigboom")
            self.game_over()

    def invader_fire(self):
        cols = {}
        for inv in self.invaders:
            if inv["alive"]:
                c = inv["rect"].centerx
                if c not in cols or inv["rect"].bottom > cols[c]["rect"].bottom:
                    cols[c] = inv
        if not cols:
            return
        shooter = random.choice(list(cols.values()))
        vy = min(420, 180 + 28 * (self.level - 1) + 60 * (1 - sum(i["alive"] for i in self.invaders) / len(self.invaders)))
        x, y = shooter["rect"].centerx, shooter["rect"].bottom + 4
        self.bullets.append({"up": False, "x": float(x), "y": float(y), "vx": 0, "vy": vy,
                             "rect": pygame.Rect(int(x) - 2, int(y) - 4, 4, 12)})
        self.sfx.play("laser")

    def kill_invader(self, inv):
        inv["alive"] = False
        pts = {"OCTO": 30, "CRAB": 20, "SQUID": 10}[inv["kind"]]
        self.score += pts
        col = INV_COLORS[inv["kind"]]
        self.explosion(inv["rect"].centerx, inv["rect"].centery, col, 16, 160)
        self.popup(str(pts), inv["rect"].centerx, inv["rect"].top - 4, (220, 235, 255), small=True)
        self.sfx.play("boom")
        self.shake = max(self.shake, 2.5)
        if random.random() < 0.14:
            self.drop_powerup(inv["rect"].centerx, inv["rect"].bottom)
        if not any(i["alive"] for i in self.invaders):
            self.state = "wave"
            self.wave_timer = 1.8
            self.popup("WAVE CLEARED", W // 2, H // 2 - 40, (255, 255, 255))
            self.sfx.play("power")
            self.level += 1
            self.new_wave()

    # ----------------------------------------------------------------- ufo
    def update_ufo(self, dt):
        alive = sum(1 for i in self.invaders if i["alive"])
        if self.ufo is None:
            self.ufo_timer -= dt
            if self.ufo_timer <= 0 and alive >= 5:
                left = random.random() < 0.5
                img = SPRITES["UFO"][0]
                self.ufo = {"x": float(-40 if left else W + 40), "dir": 1 if left else -1,
                            "rect": pygame.Rect(0, 0, img.get_width(), img.get_height()),
                            "blip": 0.0}
        else:
            u = self.ufo
            u["x"] += u["dir"] * 130 * dt
            u["rect"].center = (int(u["x"]), UFO_Y)
            u["blip"] -= dt
            if u["blip"] <= 0:
                u["blip"] = 0.4
                self.sfx.play("ufo", 0.6)
            if u["x"] < -60 or u["x"] > W + 60:
                self.ufo = None
                self.ufo_timer = random.uniform(16, 30)

    def kill_ufo(self, where):
        pts = random.choice((50, 100, 150, 300))
        self.score += pts
        self.popup(str(pts), where.centerx, where.centery, (255, 230, 120))
        self.explosion(where.centerx, where.centery, (255, 90, 90), 20, 180)
        self.shake = max(self.shake, 6)
        self.sfx.play("boom")
        self.ufo = None

    # ------------------------------------------------------------- powerups
    def drop_powerup(self, x, y):
        kind = random.choices(("rapid", "spread", "shield", "slow", "life"),
                              weights=(30, 30, 22, 14, 8))[0]
        img = self.power_sprites[kind]
        r = img.get_rect()
        r.centerx, r.top = int(x), int(y)
        self.powerups.append({"kind": kind, "rect": r})

    def update_powerups(self, dt):
        keep = []
        p = self.player
        catch = pygame.Rect(p["x"] - 22, PLAYER_Y - 4, 44, 34)
        for pu in self.powerups:
            pu["rect"].y += 105 * dt
            if self.state == "play" and pu["rect"].colliderect(catch):
                self.apply_powerup(pu["kind"])
                continue
            if pu["rect"].top > GROUND_Y + 6:
                continue
            keep.append(pu)
        self.powerups = keep

    def apply_powerup(self, kind):
        p = self.player
        now = self.t
        words = {"rapid": ("RAPID FIRE", POWER_COLORS["rapid"]),
                 "spread": ("SPREAD SHOT", POWER_COLORS["spread"]),
                 "shield": ("SHIELD UP", POWER_COLORS["shield"]),
                 "slow": ("TIME SLOW", POWER_COLORS["slow"]),
                 "life": ("EXTRA LIFE", POWER_COLORS["life"])}
        if kind == "rapid":
            p["rapid_until"] = now + 10
        elif kind == "spread":
            p["spread_until"] = now + 10
        elif kind == "shield":
            p["shield"] = True
        elif kind == "slow":
            p["slow_until"] = now + 8
        elif kind == "life":
            p["lives"] = min(5, p["lives"] + 1)
            self.sfx.play("oneup")
        else:
            self.sfx.play("power")
        self.popup(words[kind][0], p["x"], PLAYER_Y - 24, words[kind][1], small=True)

    # -------------------------------------------------------------- drawing
    def draw(self):
        b = self.board
        b.blit(self.bg, (0, 0))
        self.draw_stars(b)
        if self.state in ("play", "pause", "wave"):
            self.draw_shields(b)
            self.draw_ufo(b)
            self.draw_invaders(b)
            self.draw_powerups(b)
            self.draw_bullets(b)
            self.draw_player(b)
        self.draw_particles(b)
        self.draw_popups(b)

        s = self.screen
        s.fill((0, 0, 0))
        off = (int(random.uniform(-self.shake, self.shake)),
               int(random.uniform(-self.shake, self.shake)))
        s.blit(b, off)
        if self.state == "menu":
            self.draw_menu(s)
        elif self.state == "over":
            self.draw_over(s)
        if self.state in ("play", "pause", "wave", "over"):
            self.draw_hud(s)
        if self.state == "wave":
            self.draw_wave(s)
        if self.state == "pause":
            self.draw_pause(s)
        s.blit(self.scan, (0, 0))
        pygame.display.flip()

    def center_blit(self, surf, s, y, x=None):
        if x is None:
            x = W // 2 - surf.get_width() // 2
        s.blit(surf, (x, y))

    def draw_stars(self, s):
        for st in self.stars:
            s.fill(st["color"], (int(st["x"]), int(st["y"]), st["size"], st["size"]))

    def draw_shields(self, s):
        for b in self.bunkers:
            g = b["grid"]
            br = b["rect"]
            for gy, row in enumerate(g):
                for gx, cell in enumerate(row):
                    if cell:
                        s.fill((70, 210, 110), (br.x + gx * CS, br.y + gy * CS, CS, CS))

    def draw_ufo(self, s):
        if self.ufo is None:
            return
        u = self.ufo
        img, glow = SPRITES["UFO"][0], GLOW["UFO"][0]
        s.blit(glow, (u["rect"].centerx - glow.get_width() // 2,
                      u["rect"].centery - glow.get_height() // 2))
        s.blit(img, (u["rect"].centerx - img.get_width() // 2, u["rect"].top))

    def draw_invaders(self, s):
        fr = self.frame_idx % 2
        for inv in self.invaders:
            if not inv["alive"]:
                continue
            r = inv["rect"]
            glow = GLOW[inv["kind"]][fr]
            img = SPRITES[inv["kind"]][fr]
            s.blit(glow, (r.centerx - glow.get_width() // 2,
                          r.centery - glow.get_height() // 2))
            s.blit(img, (r.centerx - img.get_width() // 2, r.top))

    def draw_player(self, s):
        if self.state == "over":
            return
        p = self.player
        if p["inv"] > self.t and int(self.t * 14) % 2 == 0:
            return
        img, glow = SPRITES["PLAYER"][0], GLOW["PLAYER"][0]
        s.blit(glow, (p["x"] - glow.get_width() // 2,
                      PLAYER_Y + img.get_height() // 2 - glow.get_height() // 2))
        s.blit(img, (p["x"] - img.get_width() // 2, PLAYER_Y))
        if p["shield"]:
            pygame.draw.ellipse(s, (110, 255, 160),
                                (p["x"] - 26, PLAYER_Y - 12, 52, img.get_height() + 24), 2)

    def draw_bullets(self, s):
        for b in self.bullets:
            x, y = int(b["x"]), int(b["y"])
            if b["up"]:
                col, trail = (200, 255, 250), (80, 200, 220)
                pygame.draw.rect(s, trail, (x - 1, y, 2, 12))
            else:
                col, trail = (255, 240, 200), (255, 140, 80)
                pygame.draw.rect(s, trail, (x - 1, y - 12, 2, 12))
            pygame.draw.rect(s, col, (x - 2, y - 7, 4, 14))

    def draw_powerups(self, s):
        for pu in self.powerups:
            s.blit(self.power_sprites[pu["kind"]], pu["rect"])

    def draw_particles(self, s):
        for p in self.particles:
            k = max(0.0, min(1.0, p["life"] / p["max"]))
            col = tuple(int(c * k) for c in p["color"])
            s.fill(col, (int(p["x"]), int(p["y"]), p["size"], p["size"]))

    def draw_popups(self, s):
        for p in self.popups:
            img = p["font"].render(p["text"], True, p["color"])
            img.set_alpha(int(255 * max(0.0, min(1.0, p["life"]))))
            s.blit(img, (int(p["x"] - img.get_width() // 2),
                         int(p["y"] - img.get_height() // 2)))

    def draw_hud(self, s):
        s.blit(self.font.render("SCORE %06d" % self.score, True, (230, 240, 255)), (16, 12))
        s.blit(self.font.render("HI %06d" % max(self.hi, self.score), True, (150, 160, 190)),
               (W // 2 - 60, 12))
        # Wave counter sits just left of the life icons, whatever their
        # count, so the two can never collide.
        lives_left = max(0, self.player["lives"] - 1)
        icons_left = W - 24 - lives_left * 34
        wave_img = self.font.render("WAVE %d" % self.level, True, (150, 160, 190))
        wave_rect = s.blit(wave_img, (icons_left - wave_img.get_width() - 16, 12))
        icon_rects = []
        x = W - 24
        for _ in range(lives_left):
            x -= 34
            icon_rects.append(s.blit(self.life_icon, (x, 10)))
        pygame.draw.line(s, (70, 230, 210), (0, GROUND_Y + 10), (W, GROUND_Y + 10))
        return wave_rect, icon_rects

    def draw_menu(self, s):
        s.blit(self.font_big.render("COSMIC", True, (120, 255, 235)),
               (W // 2 - self.font_big.render("COSMIC", True, (120, 255, 235)).get_width() // 2, 70))
        s.blit(self.font_big.render("INVADERS", True, (255, 90, 215)),
               (W // 2 - self.font_big.render("INVADERS", True, (255, 90, 215)).get_width() // 2, 140))
        xs = (W // 2 - 230, W // 2, W // 2 + 230)
        for kind, pts, x in (("OCTO", 30, xs[0]), ("CRAB", 20, xs[1]), ("SQUID", 10, xs[2])):
            img = SPRITES[kind][int(self.t * 4) % 2]
            s.blit(img, (x - img.get_width() // 2, 260))
            label = self.font.render("%02d PTS" % pts, True, (170, 180, 210))
            s.blit(label, (x - label.get_width() // 2, 300))
        if (self.t * 2.5) % 1 < 0.65:
            self.center_blit(self.font.render("PRESS  SPACE  TO  LAUNCH", True, (255, 255, 255)), s, 390)
        self.center_blit(self.font_small.render("ARROWS / A D  --  MOVE      SPACE  --  FIRE      P  --  PAUSE",
                                                True, (140, 150, 180)), s, 450)
        if self.sfx.ok:
            self.center_blit(self.font_small.render("SOUND ON", True, (110, 220, 160)), s, 478)
        else:
            self.center_blit(self.font_small.render("SOUND OFF  --  NO AUDIO DEVICE DETECTED",
                                                    True, (255, 140, 120)), s, 478)
        if self.hi > 0:
            self.center_blit(self.font.render("HI-SCORE  %06d" % self.hi, True, (255, 230, 120)), s, 500)

    def draw_over(self, s):
        self.center_blit(self.font_big.render("GAME OVER", True, (255, 80, 80)), s, 190)
        self.center_blit(self.font.render("SCORE  %06d" % self.score, True, (230, 240, 255)), s, 290)
        if self.new_record and (self.t * 2) % 1 < 0.7:
            self.center_blit(self.font.render("NEW HIGH SCORE!", True, (255, 230, 120)), s, 330)
        self.center_blit(self.font_small.render("BEST  %06d" % self.hi, True, (150, 160, 190)), s, 365)
        if self.t > self.over_at + 1.0:  # hidden during the restart lockout
            if (self.t * 2.5) % 1 < 0.65:
                self.center_blit(self.font.render("SPACE  --  PLAY AGAIN        ESC  --  MENU", True, (200, 210, 240)), s, 440)

    def draw_wave(self, s):
        self.center_blit(self.font_big.render("WAVE %d" % self.level, True, (230, 240, 255)), s, H // 2 - 70)
        self.center_blit(self.font.render("GET READY", True, (150, 160, 190)), s, H // 2 + 5)

    def draw_pause(self, s):
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((0, 0, 20, 150))
        s.blit(ov, (0, 0))
        self.center_blit(self.font_big.render("PAUSED", True, (230, 240, 255)), s, H // 2 - 40)
        self.center_blit(self.font_small.render("P / ESC / SPACE  --  RESUME", True, (150, 160, 190)),
                         s, H // 2 + 40)


# --------------------------------------------------------------------- main
def main():
    selftest = "--selftest" in sys.argv
    # Ask for a sound device, falling back through progressively more
    # permissive formats -- if none can be opened the game simply runs
    # silent instead of crashing.
    try:
        pygame.mixer.pre_init(RATE, -16, 2, 512)
    except Exception:
        pass
    pygame.init()
    if not pygame.mixer.get_init():
        for spec in ((RATE, -16, 2, 512), (RATE, -16, 1, 512),
                     (22050, -16, 2, 512), (44100, -16, 2, 0)):
            try:
                pygame.mixer.init(*spec)
                if pygame.mixer.get_init():
                    break
            except Exception:
                pass
    try:
        pygame.mixer.set_num_channels(16)
    except Exception:
        pass
    spec = pygame.mixer.get_init()
    if spec:
        print("AUDIO: OK  --  %d Hz, %d-bit, %d channel(s), %d voices"
              % (spec[0], abs(spec[1]), spec[2], pygame.mixer.get_num_channels()))
    else:
        print("AUDIO: UNAVAILABLE -- the game will run silent.")
        print("       Check your system sound settings / output device and try again.")
    build_assets()
    game = Game(selftest)
    if game.sfx.ok and not selftest:
        # Startup jingle -- a quick, unmistakable "the sound works" check.
        pygame.time.wait(300)
        game.sfx.play("oneup")
    clock = pygame.time.Clock()
    frames = 0
    while True:
        dt = min(clock.tick(FPS) / 1000.0, 1 / 30)
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                pygame.quit()
                return
            game.handle_events(e)
        game.update(dt)
        game.draw()
        frames += 1
        if selftest and frames >= 600:
            print("SELFTEST OK  --  score: %d  state: %s  wave: %d"
                  % (game.score, game.state, game.level))
            pygame.quit()
            return


if __name__ == "__main__":
    main()