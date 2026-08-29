A collection of classic arcade games built entirely in Python and Pygame - primarily vibe coded using Qwen 3.8 27b

### The "No-Asset" Engineering Feat
The most unique feature of this project is that no external asset files (images, sounds, or music) are required. 

Every single pixel of art and every single byte of audio is generated dynamically in code at runtime:
- Procedural Art: Sprites are built using coordinate-based drawing and glow effects.
- Audio Synthesis: Sound effects are synthesized using raw waveforms (square waves, noise, and oscillators) via the math and array libraries.
- Parallax & Particles: Dynamic starfields and particle systems create a polished, retro atmosphere.

---

## Getting Started

### Prerequisites
- Python 3.x
- Pygame library

### Installation
1. Clone this repository or download the files.
2. Install the dependencies:
   ```bash
   pip install pygame
   ```

---

## The Games

### 1. Cosmic Invaders
A modern reimagining of the classic Space Invaders featuring a CRT scanline filter and synthesized retro sounds.

- Run: `python invaders.py`
- Controls:
  - Arrow Keys / A D: Move
  - SPACE (Hold): Fire
  - P / ESC: Pause
  - SPACE / ESC: Restart / Menu (on Game Over)
- Features:
  - 55-creature grid with accelerating march.
  - Destructible bunkers and bonus UFOs.
  - Power-ups: Rapid Fire, Spread Shot, Shield, Slow-Time, Extra Life.
  - Particle explosions, screen shake, and floating score text.

### 2. Asteroids
A polished, feature-rich arcade blaster with smooth 60 FPS physics and escalating difficulty.

- Run: `python asteroids.py`
- Controls:
  - LEFT / RIGHT (or A / D): Rotate
  - UP (or W): Thrust
  - SPACE: Fire (hold for auto-fire)
  - B: Detonate Bomb
  - P: Pause
  - F11: Toggle Fullscreen
  - ESC: Back to Menu / Quit
- Features:
  - Smooth inertia-based movement and screen wrapping.
  - Procedurally shaped asteroids that split into smaller pieces.
  - Wave System: Escalating difficulty with wave-clear bonuses.
  - Enemy Saucer: Appears from Wave 2 to snipe the player.
  - Power-ups: Rapid Fire, Spread Shot, Shield, and Bombs.
  - Nuke: Clear the entire screen in one blast.

---

## Self-Testing
Both games include a headless/automated self-test mode to verify that the logic and synthesis engines are working correctly without requiring a display or manual input.

- Invaders: `python invaders.py --selftest`
- Asteroids: `python asteroids.py --selftest`

---

## License
This project is free to use and modify for personal and educational purposes.
