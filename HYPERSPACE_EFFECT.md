# Hyperspace Starfield Effect - Complete Implementation Guide

A sci-fi inspired "lightspeed jump" effect using HTML5 Canvas. Stars spawn at the center and streak outward, simulating faster-than-light travel through space.

## Overview

The effect has **4 states**:
1. **IDLE** - Static twinkling stars spread across the screen (floating in space)
2. **JUMPING** - Rapid acceleration burst with screen shake and flash
3. **HYPERSPACE** - Full-speed star streaks flying outward from center
4. **DROPPING** - Deceleration back to static stars

---

## HTML Structure

```html
<!-- Starfield Canvas (behind all content) -->
<canvas id="starfield"></canvas>

<!-- Overlay Effects -->
<div class="hyperspace-flash" id="hyperspace-flash"></div>
<div class="hyperspace-tunnel" id="hyperspace-tunnel"></div>
<div class="hyperspace-glow" id="hyperspace-glow"></div>
<div class="hyperspace-vignette" id="hyperspace-vignette"></div>

<!-- Your page content goes here -->
<div class="container">
    ...
</div>
```

---

## CSS Styles

```css
/* ========================================
   STARFIELD CANVAS
   ======================================== */
#starfield {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: -1;
    pointer-events: none;
}

/* ========================================
   HYPERSPACE FLASH OVERLAY
   Brief white flash when jumping to hyperspace
   ======================================== */
.hyperspace-flash {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: -1;
    pointer-events: none;
    background: radial-gradient(ellipse at center, rgba(255,255,255,0.3) 0%, transparent 70%);
    opacity: 0;
    transition: opacity 0.1s ease;
}

.hyperspace-flash.active {
    animation: hyperspaceFlash 0.8s ease-out forwards;
}

@keyframes hyperspaceFlash {
    0% { opacity: 0; }
    15% { opacity: 1; }
    100% { opacity: 0; }
}

/* ========================================
   VIGNETTE EFFECT
   Purple-tinted edges during hyperspace
   ======================================== */
.hyperspace-vignette {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: -1;
    pointer-events: none;
    background: radial-gradient(ellipse at center, transparent 20%, rgba(139, 92, 246, 0.12) 60%, rgba(88, 28, 135, 0.25) 100%);
    opacity: 0;
    transition: opacity 0.8s ease;
}

.hyperspace-vignette.active {
    opacity: 1;
}

/* ========================================
   TUNNEL RINGS EFFECT
   Concentric circles emanating from center
   ======================================== */
.hyperspace-tunnel {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 200vmax;
    height: 200vmax;
    border-radius: 50%;
    z-index: -1;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.5s ease;
    background:
        radial-gradient(circle, transparent 0%, transparent 10%, rgba(139, 92, 246, 0.03) 10.5%, transparent 11%),
        radial-gradient(circle, transparent 0%, transparent 20%, rgba(139, 92, 246, 0.02) 20.5%, transparent 21%),
        radial-gradient(circle, transparent 0%, transparent 30%, rgba(139, 92, 246, 0.02) 30.5%, transparent 31%),
        radial-gradient(circle, transparent 0%, transparent 40%, rgba(139, 92, 246, 0.02) 40.5%, transparent 41%),
        radial-gradient(circle, transparent 0%, transparent 50%, rgba(139, 92, 246, 0.01) 50.5%, transparent 51%);
}

.hyperspace-tunnel.active {
    opacity: 1;
    animation: tunnelPulse 0.5s ease-in-out infinite alternate;
}

@keyframes tunnelPulse {
    0% { transform: translate(-50%, -50%) scale(1); }
    100% { transform: translate(-50%, -50%) scale(1.02); }
}

/* ========================================
   SCREEN SHAKE
   Applied to container during jump
   ======================================== */
.screen-shake {
    animation: screenShake 0.6s cubic-bezier(0.36, 0.07, 0.19, 0.97) both;
}

@keyframes screenShake {
    0%, 100% { transform: translateX(0); }
    10% { transform: translateX(-3px); }
    20% { transform: translateX(3px); }
    30% { transform: translateX(-2px); }
    40% { transform: translateX(2px); }
    50% { transform: translateX(-1px); }
    60% { transform: translateX(1px); }
    70% { transform: translateX(-1px); }
    80% { transform: translateX(1px); }
}

/* ========================================
   BLUE SHIFT GLOW
   Central glow during hyperspace
   ======================================== */
.hyperspace-glow {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 100%;
    height: 100%;
    z-index: -1;
    pointer-events: none;
    opacity: 0;
    background: radial-gradient(ellipse 50% 50% at center, rgba(96, 165, 250, 0.1) 0%, transparent 70%);
    transition: opacity 0.3s ease;
}

.hyperspace-glow.active {
    opacity: 1;
    animation: glowPulse 1s ease-in-out infinite alternate;
}

@keyframes glowPulse {
    0% { opacity: 0.7; }
    100% { opacity: 1; }
}
```

---

## JavaScript - Complete Starfield System

```javascript
// ============================================
// HYPERSPACE STARFIELD ANIMATION SYSTEM
// Inspired by Star Wars & Star Trek lightspeed effects
// ============================================

const Starfield = {
    // Animation states
    STATES: {
        IDLE: 'idle',           // Static twinkling stars
        JUMPING: 'jumping',     // Initial acceleration burst
        HYPERSPACE: 'hyperspace', // Full speed star streaks
        DROPPING: 'dropping'    // Deceleration back to normal
    },

    // Current state
    state: 'idle',
    canvas: null,
    ctx: null,
    stars: [],
    centerX: 0,
    centerY: 0,

    // Configuration - ADJUST THESE FOR YOUR NEEDS
    config: {
        starCount: 600,           // Stars in idle mode
        hyperspaceStarCount: 400, // Extra stars during hyperspace
        baseSpeed: 0.003,         // Idle drift speed (nearly static)
        hyperspaceSpeed: 40,      // Maximum hyperspace speed
        jumpDuration: 1500,       // Acceleration time (ms)
        dropDuration: 2000,       // Deceleration time (ms)
        maxStreakLength: 500,     // Maximum star streak length
        starColors: [
            '#ffffff',            // Pure white (most common)
            '#ffffff',
            '#ffffff',
            '#f0f4ff',            // Slight blue-white
            '#fff8f0',            // Slight warm white
            '#ffe4c4',            // Warm star
            '#e8f0ff',            // Cool white
            '#a78bfa',            // Purple accent (rare)
            '#87ceeb',            // Light blue
        ]
    },

    // Timing variables
    lastTime: 0,
    transitionStart: 0,
    animationFrame: null,

    // ==========================================
    // INITIALIZATION
    // ==========================================
    init() {
        this.canvas = document.getElementById('starfield');
        if (!this.canvas) return;

        this.ctx = this.canvas.getContext('2d');
        this.resize();
        this.createStars();
        this.animate(0);

        // Handle window resize
        window.addEventListener('resize', () => this.resize());
    },

    resize() {
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
        this.centerX = this.canvas.width / 2;
        this.centerY = this.canvas.height / 2;
    },

    // ==========================================
    // STAR CREATION
    // ==========================================
    createStars() {
        this.stars = [];
        for (let i = 0; i < this.config.starCount; i++) {
            this.stars.push(this.createStar(true));
        }
    },

    createStar(forIdle = true) {
        const angle = Math.random() * Math.PI * 2;
        const distance = Math.random() * Math.max(this.canvas.width, this.canvas.height) * 0.8;

        // Size distribution: mostly small stars, few large ones
        const sizeRand = Math.random();
        let size;
        if (sizeRand < 0.6) size = 0.5 + Math.random() * 0.5;      // 60% tiny
        else if (sizeRand < 0.85) size = 1 + Math.random() * 0.8;  // 25% small
        else if (sizeRand < 0.97) size = 1.8 + Math.random() * 1;  // 12% medium
        else size = 2.8 + Math.random() * 1.5;                      // 3% large

        return {
            // 3D position for hyperspace (x, y relative to center, z is depth)
            x: Math.cos(angle) * distance,
            y: Math.sin(angle) * distance,
            z: forIdle ? (50 + Math.random() * 200) : (1 + Math.random() * 50),

            // 2D position for idle mode
            idleX: Math.random() * (this.canvas.width || window.innerWidth),
            idleY: Math.random() * (this.canvas.height || window.innerHeight),

            // Drift direction for idle mode
            driftX: (Math.random() - 0.5) * 0.1,
            driftY: (Math.random() - 0.5) * 0.1,

            // Previous position for streak calculation
            prevX: 0,
            prevY: 0,

            // Visual properties
            baseSize: size,
            color: this.config.starColors[Math.floor(Math.random() * this.config.starColors.length)],
            twinkleOffset: Math.random() * Math.PI * 2,
            twinkleSpeed: 0.5 + Math.random() * 1.5,
            brightness: 0.4 + Math.random() * 0.6,
        };
    },

    // Reset star to center (for continuous outward flow)
    resetStar(star) {
        const angle = Math.random() * Math.PI * 2;
        const distance = 20 + Math.random() * 100;

        star.x = Math.cos(angle) * distance;
        star.y = Math.sin(angle) * distance;
        star.z = 280 + Math.random() * 70; // Large z = appears at center
        star.prevX = star.x;
        star.prevY = star.y;
    },

    // ==========================================
    // STATE TRANSITIONS
    // ==========================================

    // Call this to START hyperspace
    jumpToHyperspace() {
        if (this.state === this.STATES.HYPERSPACE || this.state === this.STATES.JUMPING) return;

        this.prepareStarsForHyperspace();
        this.state = this.STATES.JUMPING;
        this.transitionStart = performance.now();

        // Screen shake
        const container = document.querySelector('.container');
        if (container) {
            container.classList.add('screen-shake');
            setTimeout(() => container.classList.remove('screen-shake'), 600);
        }

        // Flash effect
        const flash = document.getElementById('hyperspace-flash');
        if (flash) {
            flash.classList.remove('active');
            void flash.offsetWidth; // Force reflow
            flash.classList.add('active');
        }

        // Vignette
        const vignette = document.getElementById('hyperspace-vignette');
        if (vignette) vignette.classList.add('active');

        // Tunnel (delayed)
        setTimeout(() => {
            const tunnel = document.getElementById('hyperspace-tunnel');
            if (tunnel) tunnel.classList.add('active');
        }, 300);

        // Glow (delayed)
        setTimeout(() => {
            const glow = document.getElementById('hyperspace-glow');
            if (glow) glow.classList.add('active');
        }, 500);

        // Spawn extra stars
        setTimeout(() => this.spawnHyperspaceStars(), 800);

        // Transition to full hyperspace
        setTimeout(() => {
            if (this.state === this.STATES.JUMPING) {
                this.state = this.STATES.HYPERSPACE;
            }
        }, this.config.jumpDuration);
    },

    // Call this to STOP hyperspace
    dropFromHyperspace() {
        if (this.state === this.STATES.IDLE || this.state === this.STATES.DROPPING) return;

        this.state = this.STATES.DROPPING;
        this.transitionStart = performance.now();
        this.cullExtraStars();

        // Disable effects in sequence
        const glow = document.getElementById('hyperspace-glow');
        if (glow) glow.classList.remove('active');

        setTimeout(() => {
            const tunnel = document.getElementById('hyperspace-tunnel');
            if (tunnel) tunnel.classList.remove('active');
        }, this.config.dropDuration * 0.3);

        setTimeout(() => {
            const vignette = document.getElementById('hyperspace-vignette');
            if (vignette) vignette.classList.remove('active');
        }, this.config.dropDuration * 0.7);

        setTimeout(() => {
            if (this.state === this.STATES.DROPPING) {
                this.state = this.STATES.IDLE;
            }
        }, this.config.dropDuration);
    },

    // ==========================================
    // SPEED CALCULATION
    // ==========================================
    getCurrentSpeed(timestamp) {
        const elapsed = timestamp - this.transitionStart;

        switch (this.state) {
            case this.STATES.IDLE:
                return this.config.baseSpeed;

            case this.STATES.JUMPING: {
                // Exponential acceleration (dramatic jump effect)
                const progress = Math.min(elapsed / this.config.jumpDuration, 1);
                const easeProgress = progress < 0.5
                    ? Math.pow(2, 20 * progress - 10) / 2
                    : (2 - Math.pow(2, -20 * progress + 10)) / 2;
                return this.config.baseSpeed + (this.config.hyperspaceSpeed - this.config.baseSpeed) * easeProgress;
            }

            case this.STATES.HYPERSPACE:
                // Full speed with subtle oscillation
                return this.config.hyperspaceSpeed * (0.9 + Math.sin(timestamp * 0.005) * 0.1);

            case this.STATES.DROPPING: {
                // Ease-out deceleration
                const progress = Math.min(elapsed / this.config.dropDuration, 1);
                const easeProgress = 1 - Math.pow(1 - progress, 3);
                return this.config.hyperspaceSpeed - (this.config.hyperspaceSpeed - this.config.baseSpeed) * easeProgress;
            }

            default:
                return this.config.baseSpeed;
        }
    },

    // ==========================================
    // MAIN ANIMATION LOOP
    // ==========================================
    animate(timestamp) {
        const isHyperspace = this.state === this.STATES.HYPERSPACE ||
                             this.state === this.STATES.JUMPING ||
                             this.state === this.STATES.DROPPING;

        // Clear canvas (trail effect for hyperspace, full clear for idle)
        if (isHyperspace) {
            this.ctx.fillStyle = 'rgba(10, 10, 15, 0.12)'; // Trail effect
        } else {
            this.ctx.fillStyle = 'rgba(10, 10, 15, 1)';    // Full clear
        }
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

        const speed = this.getCurrentSpeed(timestamp);

        if (this.state === this.STATES.IDLE) {
            this.drawIdleStars(timestamp);
        } else {
            this.drawHyperspaceStars(timestamp, speed);
            this.drawRadialEffect(speed);
        }

        this.animationFrame = requestAnimationFrame((t) => this.animate(t));
    },

    // ==========================================
    // IDLE MODE: Static Twinkling Stars
    // ==========================================
    drawIdleStars(timestamp) {
        for (let star of this.stars) {
            // Subtle drift
            star.idleX += star.driftX;
            star.idleY += star.driftY;

            // Wrap around screen
            if (star.idleX < -10) star.idleX = this.canvas.width + 10;
            if (star.idleX > this.canvas.width + 10) star.idleX = -10;
            if (star.idleY < -10) star.idleY = this.canvas.height + 10;
            if (star.idleY > this.canvas.height + 10) star.idleY = -10;

            // Twinkle effect
            const twinkle = 0.5 + Math.sin(timestamp * 0.002 * star.twinkleSpeed + star.twinkleOffset) * 0.5;
            const alpha = star.brightness * twinkle;

            this.ctx.beginPath();
            this.ctx.fillStyle = star.color;
            this.ctx.globalAlpha = alpha;
            this.ctx.arc(star.idleX, star.idleY, star.baseSize, 0, Math.PI * 2);
            this.ctx.fill();

            // Glow for larger stars
            if (star.baseSize > 1.8 && alpha > 0.5) {
                this.ctx.beginPath();
                this.ctx.globalAlpha = alpha * 0.2;
                this.ctx.arc(star.idleX, star.idleY, star.baseSize * 3, 0, Math.PI * 2);
                this.ctx.fill();

                // Cross flare for very bright stars
                if (star.baseSize > 2.5) {
                    this.ctx.globalAlpha = alpha * 0.15;
                    this.ctx.strokeStyle = star.color;
                    this.ctx.lineWidth = 1;

                    this.ctx.beginPath();
                    this.ctx.moveTo(star.idleX - star.baseSize * 4, star.idleY);
                    this.ctx.lineTo(star.idleX + star.baseSize * 4, star.idleY);
                    this.ctx.stroke();

                    this.ctx.beginPath();
                    this.ctx.moveTo(star.idleX, star.idleY - star.baseSize * 4);
                    this.ctx.lineTo(star.idleX, star.idleY + star.baseSize * 4);
                    this.ctx.stroke();
                }
            }

            this.ctx.globalAlpha = 1;
        }
    },

    // ==========================================
    // HYPERSPACE MODE: Outward Streaking Stars
    // ==========================================
    drawHyperspaceStars(timestamp, speed) {
        for (let star of this.stars) {
            const prevZ = star.z;

            // Move star outward (decrease z = fly toward viewer)
            star.z -= speed * 0.025;

            // 3D to 2D projection
            const factor = 300 / Math.max(0.5, star.z);
            const screenX = this.centerX + star.x * factor;
            const screenY = this.centerY + star.y * factor;

            // Previous position
            const prevFactor = 300 / Math.max(0.5, prevZ);
            const prevScreenX = this.centerX + star.x * prevFactor;
            const prevScreenY = this.centerY + star.y * prevFactor;

            // Reset if off-screen or past viewer
            if (star.z < 1 ||
                screenX < -200 || screenX > this.canvas.width + 200 ||
                screenY < -200 || screenY > this.canvas.height + 200) {
                this.resetStar(star);
                continue;
            }

            // Size based on depth (smaller z = closer = bigger)
            const size = star.baseSize * (150 / Math.max(10, star.z));

            // Streak length
            const dx = screenX - prevScreenX;
            const dy = screenY - prevScreenY;
            const streakLength = Math.min(
                Math.sqrt(dx * dx + dy * dy),
                this.config.maxStreakLength * (speed / this.config.hyperspaceSpeed)
            );

            if (streakLength > 2) {
                // Streak gradient (tail at center, head at edge)
                const gradient = this.ctx.createLinearGradient(prevScreenX, prevScreenY, screenX, screenY);

                // Blue shift at high speeds
                let streakColor = star.color;
                if (speed > this.config.hyperspaceSpeed * 0.3) {
                    const blueShift = (speed - this.config.hyperspaceSpeed * 0.3) / (this.config.hyperspaceSpeed * 0.7);
                    streakColor = this.shiftColorToBlue(star.color, blueShift * 0.4);
                }

                gradient.addColorStop(0, 'transparent');
                gradient.addColorStop(0.3, streakColor + '30');
                gradient.addColorStop(0.7, streakColor + 'a0');
                gradient.addColorStop(1, streakColor);

                this.ctx.beginPath();
                this.ctx.strokeStyle = gradient;
                this.ctx.lineWidth = Math.max(1, size * 0.6);
                this.ctx.lineCap = 'round';
                this.ctx.moveTo(prevScreenX, prevScreenY);
                this.ctx.lineTo(screenX, screenY);
                this.ctx.stroke();

                // Bright head
                this.ctx.beginPath();
                this.ctx.fillStyle = '#ffffff';
                this.ctx.globalAlpha = Math.min(0.95, 0.5 + (150 - star.z) / 200);
                this.ctx.arc(screenX, screenY, Math.max(1.2, size * 0.4), 0, Math.PI * 2);
                this.ctx.fill();
                this.ctx.globalAlpha = 1;
            } else {
                // Small dot for distant stars
                this.ctx.beginPath();
                this.ctx.fillStyle = star.color;
                this.ctx.globalAlpha = 0.6;
                this.ctx.arc(screenX, screenY, Math.max(0.5, size * 0.4), 0, Math.PI * 2);
                this.ctx.fill();
                this.ctx.globalAlpha = 1;
            }
        }
    },

    // ==========================================
    // RADIAL EFFECT: Speed lines from center
    // ==========================================
    drawRadialEffect(speed) {
        const intensity = Math.min(1, (speed - this.config.baseSpeed) / (this.config.hyperspaceSpeed - this.config.baseSpeed));
        if (intensity < 0.2) return;

        // Central vortex glow
        const gradient = this.ctx.createRadialGradient(
            this.centerX, this.centerY, 0,
            this.centerX, this.centerY, 150 * intensity
        );
        gradient.addColorStop(0, `rgba(139, 92, 246, ${intensity * 0.15})`);
        gradient.addColorStop(0.5, `rgba(96, 165, 250, ${intensity * 0.08})`);
        gradient.addColorStop(1, 'transparent');

        this.ctx.fillStyle = gradient;
        this.ctx.beginPath();
        this.ctx.arc(this.centerX, this.centerY, 200, 0, Math.PI * 2);
        this.ctx.fill();

        // Radial speed lines
        const numLines = 24;
        this.ctx.lineWidth = 1;

        for (let i = 0; i < numLines; i++) {
            const angle = (i / numLines) * Math.PI * 2;
            const innerRadius = 80 + Math.sin(performance.now() * 0.003 + i) * 20;
            const outerRadius = Math.max(this.canvas.width, this.canvas.height) * 0.8;

            const lineGradient = this.ctx.createLinearGradient(
                this.centerX + Math.cos(angle) * innerRadius,
                this.centerY + Math.sin(angle) * innerRadius,
                this.centerX + Math.cos(angle) * outerRadius,
                this.centerY + Math.sin(angle) * outerRadius
            );
            lineGradient.addColorStop(0, `rgba(139, 92, 246, ${intensity * 0.1})`);
            lineGradient.addColorStop(0.3, `rgba(96, 165, 250, ${intensity * 0.05})`);
            lineGradient.addColorStop(1, 'transparent');

            this.ctx.strokeStyle = lineGradient;
            this.ctx.beginPath();
            this.ctx.moveTo(
                this.centerX + Math.cos(angle) * innerRadius,
                this.centerY + Math.sin(angle) * innerRadius
            );
            this.ctx.lineTo(
                this.centerX + Math.cos(angle) * outerRadius,
                this.centerY + Math.sin(angle) * outerRadius
            );
            this.ctx.stroke();
        }

        // Pulsing center point
        const pulseSize = 3 + Math.sin(performance.now() * 0.01) * 2;
        this.ctx.fillStyle = `rgba(255, 255, 255, ${intensity * 0.3})`;
        this.ctx.beginPath();
        this.ctx.arc(this.centerX, this.centerY, pulseSize, 0, Math.PI * 2);
        this.ctx.fill();
    },

    // ==========================================
    // HELPER FUNCTIONS
    // ==========================================

    // Shift color toward blue (Doppler effect simulation)
    shiftColorToBlue(color, amount) {
        const colorMap = {
            '#ffffff': [255, 255, 255],
            '#f0f4ff': [240, 244, 255],
            '#fff8f0': [255, 248, 240],
            '#ffe4c4': [255, 228, 196],
            '#e8f0ff': [232, 240, 255],
            '#a78bfa': [167, 139, 250],
            '#87ceeb': [135, 206, 235],
            '#22d3ee': [34, 211, 238]
        };

        const rgb = colorMap[color] || [255, 255, 255];
        const targetR = Math.round(rgb[0] * (1 - amount) + 150 * amount);
        const targetG = Math.round(rgb[1] * (1 - amount) + 200 * amount);
        const targetB = Math.round(rgb[2] * (1 - amount * 0.3) + 255 * amount * 0.3);

        const toHex = (n) => Math.min(255, Math.max(0, n)).toString(16).padStart(2, '0');
        return `#${toHex(targetR)}${toHex(targetG)}${toHex(targetB)}`;
    },

    // Prepare stars for hyperspace transition
    prepareStarsForHyperspace() {
        for (let star of this.stars) {
            const angle = Math.random() * Math.PI * 2;
            const distance = 20 + Math.random() * 150;

            star.x = Math.cos(angle) * distance;
            star.y = Math.sin(angle) * distance;
            star.z = 150 + Math.random() * 200;
            star.prevX = star.x;
            star.prevY = star.y;
        }
    },

    // Add extra stars during hyperspace
    spawnHyperspaceStars() {
        const extraStars = this.config.hyperspaceStarCount;
        for (let i = 0; i < extraStars; i++) {
            const star = this.createStar(false);
            star.z = 200 + Math.random() * 150;
            this.stars.push(star);
        }
    },

    // Remove extra stars when dropping
    cullExtraStars() {
        if (this.stars.length > this.config.starCount) {
            this.stars.length = this.config.starCount;
        }
        for (let star of this.stars) {
            star.idleX = Math.random() * this.canvas.width;
            star.idleY = Math.random() * this.canvas.height;
        }
    }
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    Starfield.init();
});
```

---

## Usage

```javascript
// Start the hyperspace effect (e.g., when a task begins)
Starfield.jumpToHyperspace();

// Stop the hyperspace effect (e.g., when task completes)
Starfield.dropFromHyperspace();
```

---

## Customization Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `starCount` | 600 | Number of stars in idle mode |
| `hyperspaceStarCount` | 400 | Extra stars added during hyperspace |
| `baseSpeed` | 0.003 | Drift speed in idle mode |
| `hyperspaceSpeed` | 40 | Maximum speed during hyperspace |
| `jumpDuration` | 1500ms | Time to accelerate to hyperspace |
| `dropDuration` | 2000ms | Time to decelerate back to idle |
| `maxStreakLength` | 500 | Maximum pixel length of star streaks |
| `starColors` | Array | Color palette for stars |

---

## Visual Effects Breakdown

1. **Screen Shake** - Brief container shake when jumping (0.6s)
2. **Flash** - Radial white flash burst (0.8s)
3. **Vignette** - Purple-tinted edges that persist during hyperspace
4. **Tunnel** - Concentric pulsing rings from center
5. **Glow** - Central blue glow that pulses
6. **Star Streaks** - Main canvas animation with gradient trails
7. **Radial Lines** - Subtle speed lines emanating from center
8. **Blue Shift** - Colors shift toward blue at high speeds (Doppler effect)

---

## Performance Notes

- Canvas uses `requestAnimationFrame` for smooth 60fps
- Trail effect achieved by clearing with semi-transparent overlay
- Stars are recycled (not recreated) for efficiency
- Extra hyperspace stars are culled when dropping back to idle
- Typical memory: ~5-10MB for canvas operations
