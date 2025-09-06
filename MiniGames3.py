"""
Galactic Defender — mini-game kompleks (single-file)
Features:
 - OOP design, state machine (MENU, PLAY, PAUSE, SHOP, GAMEOVER)
 - Player movement (8-dir), multiple weapon modes (single, spread, laser), dash
 - Enemy varieties (chaser, shooter, wave, boss-like), enemy spawners & wave system
 - Power-ups (heal, rapid fire, shield, bomb, coin)
 - In-game shop (spend coins to buy upgrades/permanent unlocks)
 - Particle system (explosions, trails)
 - Simple procedural levels/waves, difficulty scaling
 - Save/load (hiscore + persistent upgrades) to JSON file
 - Keyboard + optional joystick support, synthetic sounds (if pygame.mixer available)
 - All rendering using primitives (no external images)
Controls:
 - Move: WASD or arrow keys
 - Shoot: Z / J / Left Ctrl
 - Switch weapon: Q / E
 - Dash: Space / Left Shift
 - Bomb: X / K
 - Pause: P / Esc
 - Open Shop (when available between waves): S
Requirements: pygame
Run: python galactic_defender.py
"""

import pygame, sys, random, math, json, os, time
from collections import deque

# ---------------- CONFIG ----------------
WIDTH, HEIGHT = 1000, 650
FPS = 60
SAVE_FILE = "galactic_save.json"
FONT_NAME = "consolas"
# gameplay tuning
PLAYER_MAX_HP = 120
PLAYER_BASE_SPEED = 300
PLAYER_DASH_SPEED = 700
PLAYER_DASH_COOLDOWN = 1.0
BULLET_SPEED = 700
LASER_DURATION = 0.25

# ---------------- UTIL ----------------
def clamp(v, lo, hi): return max(lo, min(hi, v))
def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except:
        pass
    return default
def save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print("Save failed:", e)

# ---------------- SOUND HELPER ----------------
def try_mixer():
    try:
        pygame.mixer.init()
        return True
    except:
        return False

def tone(freq=440, ms=120, vol=0.2):
    # generate simple beep if mixer present
    sr = 22050
    n = int(sr * ms / 1000)
    buf = bytearray()
    for i in range(n):
        v = int(127 * math.sin(2 * math.pi * freq * i / sr))
        buf += int.to_bytes((v+128) % 256, 1, 'little', signed=False)
    try:
        snd = pygame.mixer.Sound(buffer=bytes(buf))
        snd.set_volume(vol)
        return snd
    except:
        return None

# ---------------- PARTICLES ----------------
class Particle:
    def __init__(self, x, y, vx, vy, color, life, r):
        self.x = x; self.y = y
        self.vx = vx; self.vy = vy
        self.color = color
        self.life = life; self.t = 0
        self.r = r

    def update(self, dt):
        self.t += dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vx *= 0.98; self.vy *= 0.98
        return self.t < self.life

    def draw(self, surf):
        alpha = int(255 * max(0, 1 - self.t / self.life))
        s = pygame.Surface((self.r*2, self.r*2), pygame.SRCALPHA)
        s.fill((0,0,0,0))
        pygame.draw.circle(s, (*self.color, alpha), (self.r, self.r), self.r)
        surf.blit(s, (self.x - self.r, self.y - self.r))

class ParticleSystem:
    def __init__(self):
        self.ps = []

    def emit_explosion(self, x, y, color=(255,160,60), amount=30, speed=200):
        for _ in range(amount):
            ang = random.random() * math.tau
            spd = random.uniform(0.2*speed, speed)
            vx = math.cos(ang) * spd; vy = math.sin(ang) * spd
            r = random.randint(2,4)
            life = random.uniform(0.3, 0.9)
            self.ps.append(Particle(x,y,vx,vy,color,life,r))

    def emit_trail(self, x, y, color=(150,200,255)):
        vx = random.uniform(-30,30); vy = random.uniform(-30,30)
        r = random.randint(1,3); life = random.uniform(0.2,0.45)
        self.ps.append(Particle(x,y,vx,vy,color,life,r))

    def update(self, dt):
        self.ps = [p for p in self.ps if p.update(dt)]

    def draw(self, surf):
        for p in self.ps: p.draw(surf)

# ---------------- ENTITIES ----------------
class Bullet:
    def __init__(self, x,y, vx, vy, owner='player', dmg=12, color=(180,255,200), r=4):
        self.x=x; self.y=y; self.vx=vx; self.vy=vy; self.owner=owner; self.dmg=dmg; self.color=color; self.r=r
    def update(self, dt): self.x += self.vx*dt; self.y += self.vy*dt
    def alive(self): return -50 < self.x < WIDTH+50 and -50 < self.y < HEIGHT+50
    def draw(self,surf): pygame.draw.circle(surf, self.color, (int(self.x),int(self.y)), self.r)

class LaserBeam:
    def __init__(self, x,y, dx,dy, life=LASER_DURATION, dmg=6):
        self.x=x; self.y=y; self.dx=dx; self.dy=dy; self.life=life; self.t=0; self.dmg=dmg
    def update(self, dt): self.t+=dt
    def alive(self): return self.t<self.life
    def draw(self, surf):
        alpha = int(255 * (1 - self.t/self.life))
        endx = self.x + self.dx*2000; endy = self.y + self.dy*2000
        s = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        pygame.draw.line(s, (120,255,200,alpha), (int(self.x),int(self.y)), (int(endx),int(endy)), 3)
        surf.blit(s,(0,0))

class Player:
    def __init__(self, x,y):
        self.x=x; self.y=y; self.r=16
        self.hp=PLAYER_MAX_HP; self.maxhp=PLAYER_MAX_HP
        self.speed=PLAYER_BASE_SPEED
        self.dash_cd=0; self.dash_time=0
        self.coins=0; self.score=0
        self.weapon_index = 0
        self.weapons = ['single','spread','laser']
        self.bullets_cool=0
        self.rapid=0
        self.shield=0
        self.bombs=2
        self.upgrades = {"hp":0,"speed":0,"damage":0}
    def rect(self): return pygame.Rect(int(self.x-self.r), int(self.y-self.r), self.r*2, self.r*2)
    def switch_weapon(self,dirn):
        self.weapon_index = (self.weapon_index + dirn) % len(self.weapons)
    def update(self, dt):
        self.dash_cd = max(0,self.dash_cd-dt)
        self.bullets_cool = max(0,self.bullets_cool-dt)
        self.rapid = max(0,self.rapid-dt)
        self.shield = max(0,self.shield-dt)
    def draw(self, surf):
        # shield glow
        if self.shield>0:
            s = pygame.Surface((self.r*4, self.r*4), pygame.SRCALPHA)
            a = 120 + int(40*math.sin(pygame.time.get_ticks()*0.01))
            pygame.draw.circle(s, (120,200,255,a), (self.r*2,self.r*2), int(self.r*1.8), 3)
            surf.blit(s, (self.x-self.r*2, self.y-self.r*2))
        pygame.draw.circle(surf, (80,200,255), (int(self.x),int(self.y)), self.r)
        # direction marker
        pygame.draw.circle(surf, (220,255,255), (int(self.x+0), int(self.y-self.r-6)), 3)

# Enemy types with simple AI
class Enemy:
    def __init__(self, x,y, kind='chaser', level=1):
        self.x=x; self.y=y; self.kind=kind; self.level=level
        basehp = 20 + level*6
        self.hp = basehp if kind!='boss' else basehp*6
        self.r = 12 if kind!='boss' else 36
        self.speed = 90 + level*8 if kind!='boss' else 45
        self.t = 0
        self.cool= random.uniform(0.6,1.8)
        self.color = (255,120,120) if kind=='chaser' else (255,200,120) if kind=='shooter' else (180,120,255)
    def rect(self): return pygame.Rect(int(self.x-self.r), int(self.y-self.r), self.r*2, self.r*2)
    def update(self, dt, player, bullets):
        self.t += dt
        if self.kind == 'chaser':
            dx = player.x - self.x; dy = player.y - self.y
            d = math.hypot(dx,dy)+1e-6
            self.x += dx/d * self.speed * dt; self.y += dy/d * self.speed * dt
        elif self.kind == 'zig':
            dx = player.x - self.x; dy = player.y - self.y
            d = math.hypot(dx,dy)+1e-6
            perpx, perpy = -dy/d, dx/d
            wav = math.sin(self.t*4)*80
            self.x += (dx/d * (self.speed*0.9) + perpx*wav*0.01) * dt
            self.y += (dy/d * (self.speed*0.9) + perpy*wav*0.01) * dt
        elif self.kind == 'shooter':
            dx = player.x - self.x; dy = player.y - self.y
            d = math.hypot(dx,dy)+1e-6
            self.x += dx/d * (self.speed*0.6) * dt; self.y += dy/d * (self.speed*0.6) * dt
            self.cool -= dt
            if self.cool <= 0:
                self.cool = 0.9 - min(0.5, self.level*0.03)
                vx = dx/d * (BULLET_SPEED*0.6); vy = dy/d * (BULLET_SPEED*0.6)
                bullets.append(Bullet(self.x, self.y, vx, vy, owner='enemy', dmg=8, color=(255,160,220), r=4))
        elif self.kind == 'boss':
            # slow movement, shoot in bursts
            self.cool -= dt
            if self.cool <= 0:
                self.cool = 0.35
                for ang in range(0,360,30):
                    rad = math.radians(ang + int(self.t*40)%360)
                    vx = math.cos(rad)*200; vy = math.sin(rad)*200
                    bullets.append(Bullet(self.x, self.y, vx, vy, owner='enemy', dmg=10, color=(255,200,80), r=5))
        # clamp
        self.x = clamp(self.x, -100, WIDTH+100)
        self.y = clamp(self.y, -100, HEIGHT+100)

# ---------------- GAME ----------------
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Galactic Defender")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(FONT_NAME, 18)
        self.big = pygame.font.SysFont(FONT_NAME, 44, bold=True)
        self.running = True
        self.state = "menu"
        self.particles = ParticleSystem()
        self.load_save()
        self.init_audio()
        self.reset_run()
        self.joystick = None
        if pygame.joystick.get_count()>0:
            try:
                self.joystick = pygame.joystick.Joystick(0); self.joystick.init()
            except: self.joystick=None

    def init_audio(self):
        self.sounds = {}
        self.have_sound = try_mixer()
        if self.have_sound:
            self.sounds['shoot'] = tone(880,60,0.08)
            self.sounds['hit']   = tone(300,90,0.09)
            self.sounds['expl']  = tone(120,180,0.2)
            self.sounds['pickup']= tone(1000,120,0.12)
        else:
            self.sounds = None

    def load_save(self):
        data = load_json(SAVE_FILE, {"hiscore":0,"upgrades":{}})
        self.hiscore = data.get("hiscore",0)
        self.persist_upgrades = data.get("upgrades",{"hp":0,"speed":0,"damage":0})
    def save(self):
        save_json(SAVE_FILE, {"hiscore":self.hiscore,"upgrades":self.persist_upgrades})

    def reset_run(self):
        self.player = Player(WIDTH*0.5, HEIGHT*0.7)
        # apply persistent upgrades:
        self.player.maxhp = PLAYER_MAX_HP + self.persist_upgrades.get("hp",0)*20
        self.player.hp = self.player.maxhp
        self.player.speed = PLAYER_BASE_SPEED + self.persist_upgrades.get("speed",0)*30
        self.enemies = []
        self.bullets = []
        self.lasers = []
        self.wave = 0
        self.wave_time = 0
        self.spawn_timer = 0
        self.wave_state = "interlude"  # interlude between waves (shop available)
        self.interlude_time = 4.0
        self.difficulty = 1.0

    def start_game(self):
        self.reset_run()
        self.state = "play"

    def spawn_enemy_edge(self, kind=None, level=1):
        side = random.choice(['top','bottom','left','right'])
        if side=='top': x = random.randint(50, WIDTH-50); y = -40
        elif side=='bottom': x = random.randint(50, WIDTH-50); y = HEIGHT+40
        elif side=='left': x = -40; y = random.randint(50, HEIGHT-50)
        else: x = WIDTH+40; y = random.randint(50, HEIGHT-50)
        k = kind if kind else random.choices(['chaser','shooter','zig'], weights=[0.5,0.25,0.25])[0]
        self.enemies.append(Enemy(x,y,k,level))

    def spawn_wave(self):
        self.wave += 1
        self.difficulty = 1 + self.wave*0.12
        n = min(4 + self.wave*2, 40)
        for i in range(n):
            lvl = 1 + self.wave//3
            self.spawn_enemy_edge(level=lvl)
        # occasionally spawn a mini-boss
        if self.wave % 5 == 0:
            self.enemies.append(Enemy(WIDTH/2, -120, kind='boss', level=3 + self.wave//5))

    def input_play(self, dt):
        keys = pygame.key.get_pressed()
        move_x = 0; move_y = 0
        # joystick
        if self.joystick:
            ax0 = self.joystick.get_axis(0); ax1 = self.joystick.get_axis(1)
            if abs(ax0) > 0.1: move_x = ax0
            if abs(ax1) > 0.1: move_y = ax1
        # keyboard
        if keys[pygame.K_a] or keys[pygame.K_LEFT]: move_x -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]: move_x += 1
        if keys[pygame.K_w] or keys[pygame.K_UP]: move_y -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]: move_y += 1

        # normalize
        vlen = math.hypot(move_x, move_y)
        if vlen>0:
            move_x /= vlen; move_y /= vlen

        # dash
        dash_used = False
        if (keys[pygame.K_SPACE] or keys[pygame.K_LSHIFT]) and self.player.dash_cd<=0:
            self.player.dash_cd = PLAYER_DASH_COOLDOWN
            self.player.x += move_x * PLAYER_DASH_SPEED * 0.12
            self.player.y += move_y * PLAYER_DASH_SPEED * 0.12
            self.particles.emit_trail(self.player.x, self.player.y)
            dash_used = True

        # movement
        self.player.x += move_x * self.player.speed * dt
        self.player.y += move_y * self.player.speed * dt
        self.player.x = clamp(self.player.x, 20, WIDTH-20)
        self.player.y = clamp(self.player.y, 20, HEIGHT-20)

        # shooting
        shoot = keys[pygame.K_z] or keys[pygame.K_j] or (self.joystick and self.joystick.get_button(0))
        switch_left = keys[pygame.K_q]
        switch_right = keys[pygame.K_e]
        bomb = keys[pygame.K_x] or keys[pygame.K_k]
        # switch weapons
        if switch_left:
            self.player.switch_weapon(-1)
        if switch_right:
            self.player.switch_weapon(1)
        # bomb
        if bomb and self.player.bombs>0 and (time.time() - getattr(self,'last_bomb',0))>0.5:
            self.player.bombs -= 1; self.last_bomb = time.time()
            self.bomb_explode()
            if self.sounds: self.sounds.get('expl') and self.sounds['expl'].play()

        # fire mechanics depending on weapon
        if shoot:
            w = self.player.weapons[self.player.weapon_index]
            if w == 'single':
                rate = 0.16 * (0.6 if self.player.rapid>0 else 1.0)
                if self.player.bullets_cool <= 0:
                    self.player.bullets_cool = rate
                    dir_x, dir_y = 0, -1
                    vx = dir_x * BULLET_SPEED; vy = dir_y * BULLET_SPEED
                    dmg = 12 + self.player.upgrades.get('damage',0)*2
                    self.bullets.append(Bullet(self.player.x, self.player.y-18, vx, vy, owner='player', dmg=dmg, color=(120,255,200)))
                    if self.sounds: self.sounds['shoot'].play()
            elif w == 'spread':
                rate = 0.26 * (0.6 if self.player.rapid>0 else 1.0)
                if self.player.bullets_cool <= 0:
                    self.player.bullets_cool = rate
                    angs = [-18,0,18]
                    for a in angs:
                        rad = math.radians(a-90)
                        vx = math.cos(rad)*BULLET_SPEED; vy = math.sin(rad)*BULLET_SPEED
                        self.bullets.append(Bullet(self.player.x, self.player.y-18, vx, vy, owner='player', dmg=10+self.player.upgrades.get('damage',0)))
                    if self.sounds: self.sounds['shoot'].play()
            elif w == 'laser':
                rate = 0.38 * (0.6 if self.player.rapid>0 else 1.0)
                if self.player.bullets_cool <= 0:
                    self.player.bullets_cool = rate
                    dir_x, dir_y = 0, -1
                    # create a short laser
                    self.lasers.append(LaserBeam(self.player.x, self.player.y-10, dir_x, dir_y, life=LASER_DURATION, dmg=6+self.player.upgrades.get('damage',0)))
                    if self.sounds: self.sounds['shoot'] and self.sounds['shoot'].play()

    def bomb_explode(self):
        # clear enemies in radius
        rad = 180
        killed = 0
        for e in list(self.enemies):
            if (e.x - self.player.x)**2 + (e.y - self.player.y)**2 <= rad*rad:
                self.particles.emit_explosion(e.x, e.y, amount=18)
                try:
                    self.enemies.remove(e)
                    killed += 1
                    self.player.score += 15
                except:
                    pass
        if killed>0:
            self.player.coins += killed*2

    def update_physics(self, dt):
        # update player cooldowns
        self.player.update(dt)
        # update bullets
        new_bullets = []
        for b in self.bullets:
            b.update(dt)
            if b.alive(): new_bullets.append(b)
        self.bullets = new_bullets
        # update lasers
        self.lasers = [l for l in self.lasers if l.alive()]
        for l in self.lasers:
            l.update(dt)
        # update enemies
        for e in list(self.enemies):
            e.update(dt, self.player, self.bullets)
            if e.hp <= 0:
                self.particles.emit_explosion(e.x, e.y, amount=14, color=(255,220,180))
                self.enemies.remove(e)
                self.player.score += 10 + e.level*3
                self.player.coins += 1 + e.level//2
                # small chance drop a powerup
                if random.random() < 0.18:
                    self.drop_powerup(e.x, e.y)
        # check collisions: bullets -> enemies, enemy bullets -> player
        for b in list(self.bullets):
            if b.owner == 'player':
                for e in list(self.enemies):
                    if (e.x - b.x)**2 + (e.y - b.y)**2 <= (e.r + b.r)**2:
                        e.hp -= b.dmg
                        try:
                            self.bullets.remove(b)
                        except: pass
                        break
            else:
                # enemy bullet hits player
                if (self.player.x - b.x)**2 + (self.player.y - b.y)**2 <= (self.player.r + b.r)**2:
                    if self.player.shield <= 0:
                        self.player.hp -= b.dmg
                    try: self.bullets.remove(b)
                    except: pass
        # lasers damage
        for l in list(self.lasers):
            for e in list(self.enemies):
                # approximate: line intersects circle -> check distance from center to line
                px,py = e.x, e.y
                x1,y1 = l.x, l.y
                x2,y2 = l.x + l.dx*2000, l.y + l.dy*2000
                # distance point to line segment (infinite segment ok)
                num = abs((y2-y1)*px - (x2-x1)*py + x2*y1 - y2*x1)
                den = math.hypot(y2-y1, x2-x1)+1e-6
                dist = num/den
                if dist <= e.r + 4:
                    e.hp -= l.dmg*dt*8  # continuous damage scale
        # enemies collide with player
        for e in list(self.enemies):
            if (e.x - self.player.x)**2 + (e.y - self.player.y)**2 <= (e.r + self.player.r)**2:
                if self.player.shield <= 0:
                    self.player.hp -= 18
                try:
                    self.enemies.remove(e)
                except: pass
                self.particles.emit_explosion(self.player.x, self.player.y, color=(255,120,120), amount=20)
        # particles
        self.particles.update(dt)

    def drop_powerup(self, x, y):
        kinds = ['heal','rapid','shield','bomb','coin']
        k = random.choice(kinds)
        self.powerups.append({'x':x,'y':y,'type':k,'t':0})

    def update_powerups(self, dt):
        for p in list(self.powerups):
            p['y'] += 40*dt
            p['t'] += dt
            if (p['x']-self.player.x)**2 + (p['y']-self.player.y)**2 <= (self.player.r + 12)**2:
                # pickup
                if p['type']=='heal':
                    self.player.hp = clamp(self.player.hp + 40, 0, self.player.maxhp)
                elif p['type']=='rapid':
                    self.player.rapid = 6.0
                elif p['type']=='shield':
                    self.player.shield = 6.0
                elif p['type']=='bomb':
                    self.player.bombs = clamp(self.player.bombs+1, 0, 6)
                elif p['type']=='coin':
                    self.player.coins += 5
                if self.sounds: self.sounds.get('pickup') and self.sounds['pickup'].play()
                try: self.powerups.remove(p)
                except: pass
            elif p['y'] > HEIGHT+40:
                try: self.powerups.remove(p)
                except: pass

    def update_wave_and_spawning(self, dt):
        # handle interlude
        if self.wave_state == 'interlude':
            self.interlude_time -= dt
            if self.interlude_time <= 0:
                self.wave_state = 'active'
                self.spawn_wave()
        elif self.wave_state == 'active':
            # if no enemies, go to interlude
            if not self.enemies:
                self.wave_state = 'interlude'
                self.interlude_time = 6.0
                # allow opening shop in interlude
                self.last_interlude = time.time()
            # spawn a few extra occasionally
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                self.spawn_timer = max(0.3, 1.2 / (1 + self.wave*0.08))
                if random.random() < 0.6:
                    self.spawn_enemy_edge(level=1 + self.wave//2)

    def draw_hud(self):
        # HP bar
        pygame.draw.rect(self.screen, (40,40,60), (18, 14, 260, 18), border_radius=6)
        pct = self.player.hp / self.player.maxhp
        pygame.draw.rect(self.screen, (120,220,120), (18, 14, int(260*pct), 18), border_radius=6)
        self.screen.blit(self.font.render(f"HP {int(self.player.hp)}/{int(self.player.maxhp)}", True, (230,230,230)), (22,36))
        # Score/coins
        self.screen.blit(self.font.render(f"Score: {int(self.player.score)}  Coins: {int(self.player.coins)}  Bombs: {self.player.bombs}", True, (220,220,240)), (18, 58))
        self.screen.blit(self.font.render(f"Wave: {self.wave}  Hi: {int(self.hiscore)}  Weapon: {self.player.weapons[self.player.weapon_index]}", True, (200,200,220)), (18, 84))
        # controls hint
        hint = "Move WASD/Arrow  Shoot Z/J  Switch Q/E  Dash Space  Bomb X  Pause P  Shop S(Interlude)"
        t = self.font.render(hint, True, (120,130,150))
        self.screen.blit(t, (WIDTH - t.get_width() - 12, HEIGHT - 28))

    def draw(self, dt):
        # background gradient
        self.screen.fill((8,10,18))
        for i in range(8):
            col = 18 + i*6
            pygame.draw.rect(self.screen, (col+20, col+10, col+35), (0, i*(HEIGHT//8), WIDTH, HEIGHT//8))
        # stars (simple)
        for i in range(40):
            x = (i*37 + int(time.time()*20)%WIDTH) % WIDTH
            y = (i*61 + int(time.time()*12)%HEIGHT) % HEIGHT
            self.screen.set_at((x%WIDTH, y%HEIGHT), (200,200,230))

        # draw powerups
        for p in self.powerups:
            color = (120,255,120) if p['type']=='heal' else (120,180,255) if p['type']=='rapid' else (200,220,255) if p['type']=='shield' else (255,180,120) if p['type']=='bomb' else (255,240,120)
            pygame.draw.circle(self.screen, color, (int(p['x']), int(p['y'])), 10, 2)

        # draw enemies
        for e in self.enemies:
            pygame.draw.circle(self.screen, e.color, (int(e.x), int(e.y)), e.r)
            # HP bar small
            ratio = clamp(e.hp / (20 + e.level*6), 0, 1)
            w = int(e.r*2*ratio)
            pygame.draw.rect(self.screen, (50,50,70), (int(e.x-e.r), int(e.y-e.r-8), e.r*2, 4))
            pygame.draw.rect(self.screen, (200,80,80), (int(e.x-e.r), int(e.y-e.r-8), w, 4))

        # draw bullets
        for b in self.bullets: b.draw(self.screen)
        # lasers
        for l in self.lasers: l.draw(self.screen)
        # draw player
        self.player.draw(self.screen)
        # particles
        self.particles.draw(self.screen)
        # hud
        self.draw_hud()
        # interlude/shop hint
        if self.wave_state == 'interlude':
            txt = self.big.render("INTERLUDE - Press S to Open Shop", True, (200,200,255))
            self.screen.blit(txt, ((WIDTH-txt.get_width())//2, 120))

    def run(self):
        # main loop
        dt = 0
        self.powerups = []
        FPS = 60
        last_time = time.time()
        while self.running:
            now = time.time(); dt = now - last_time; last_time = now
            # event polling
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    self.running = False
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_p or e.key == pygame.K_ESCAPE:
                        if self.state == 'play': self.state = 'pause'
                        elif self.state == 'pause': self.state = 'play'
                    if e.key == pygame.K_s and self.wave_state=='interlude' and self.state=='play':
                        self.state = 'shop'
                    if e.key == pygame.K_m and self.state != 'menu':
                        self.state = 'menu'
                if e.type == pygame.JOYBUTTONDOWN:
                    pass
            if self.state == 'menu':
                self.menu_loop(dt)
            elif self.state == 'play':
                self.input_play(dt)
                self.update_physics(dt)
                self.update_powerups(dt)
                self.update_wave_and_spawning(dt)
                self.draw(dt)
                # check player death
                if self.player.hp <= 0:
                    if self.player.score > self.hiscore:
                        self.hiscore = int(self.player.score)
                    self.state = 'gameover'
                pygame.display.flip()
            elif self.state == 'pause':
                self.draw(dt)
                self.pause_screen()
            elif self.state == 'shop':
                self.shop_loop()
            elif self.state == 'gameover':
                self.gameover_loop()
            # cap framerate
            self.clock.tick(FPS)
        self.save()
        pygame.quit()
        sys.exit()

    # ---------- Screens ----------
    def menu_loop(self, dt):
        # simple menu
        self.screen.fill((6,8,12))
        title = self.big.render("GALACTIC DEFENDER", True, (160,220,255))
        self.screen.blit(title, ((WIDTH-title.get_width())//2, 120))
        hint = self.font.render("Press ENTER to Start   |   H = How to Play   |   Q = Quit", True, (200,200,200))
        self.screen.blit(hint, ((WIDTH-hint.get_width())//2, 220))
        scoretxt = self.font.render(f"Hi-Score: {self.hiscore}", True, (200,200,240))
        self.screen.blit(scoretxt, ((WIDTH-scoretxt.get_width())//2, 280))
        pygame.display.flip()
        for e in pygame.event.get():
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_RETURN:
                    self.start_game()
                elif e.key == pygame.K_q:
                    self.running = False
                elif e.key == pygame.K_h:
                    self.howto_screen()

    def howto_screen(self):
        showing = True
        while showing:
            self.screen.fill((10,12,18))
            lines = [
                "How to Play:",
                "Move: WASD / Arrow keys",
                "Shoot: Z / J",
                "Switch Weapon: Q / E",
                "Dash: Space",
                "Bomb: X (consumable)",
                "Interludes between waves allow Shop (press S)",
                "Pick up powerups for temporary boosts",
                "Press any key to return"
            ]
            y = 120
            for ln in lines:
                self.screen.blit(self.font.render(ln, True, (220,220,220)), (120,y)); y+=30
            pygame.display.flip()
            for e in pygame.event.get():
                if e.type == pygame.KEYDOWN:
                    showing = False
                if e.type == pygame.QUIT:
                    showing = False; self.running=False

    def pause_screen(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0,0,0,150))
        self.screen.blit(overlay, (0,0))
        t = self.big.render("PAUSED", True, (240,240,255))
        self.screen.blit(t, ((WIDTH-t.get_width())//2, HEIGHT//2-40))
        pygame.display.flip()
        # unpause handled in event loop

    def shop_loop(self):
        # very simple shop UI
        sel = 0
        opts = [
            ("Max HP +20", "hp", 8),
            ("Speed +10", "speed", 10),
            ("Damage +1", "damage", 12),
            ("Extra Bomb", "bomb", 6),
            ("Restore HP", "heal", 5)
        ]
        while self.state == 'shop':
            self.screen.fill((12,14,22))
            title = self.big.render("SHOP", True, (200,220,255)); self.screen.blit(title, ((WIDTH-title.get_width())//2, 80))
            y = 180
            for i,(label,key,cost) in enumerate(opts):
                col = (200,255,200) if i==sel else (180,200,220)
                self.screen.blit(self.font.render(f"{label} — {cost} coins", True, col), (WIDTH//3, y)); y+=36
            hint = self.font.render("Use Up/Down, Enter to buy, Esc to exit", True, (160,160,180))
            self.screen.blit(hint, ((WIDTH-hint.get_width())//2, HEIGHT-80))
            self.screen.blit(self.font.render(f"Coins: {self.player.coins}", True, (255,240,200)), (WIDTH-200, 120))
            pygame.display.flip()
            for e in pygame.event.get():
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_UP: sel = (sel-1) % len(opts)
                    if e.key == pygame.K_DOWN: sel = (sel+1) % len(opts)
                    if e.key == pygame.K_RETURN:
                        label,key,cost = opts[sel]
                        if self.player.coins >= cost:
                            self.player.coins -= cost
                            if key in ('hp','speed','damage'):
                                self.persist_upgrades[key] = self.persist_upgrades.get(key,0) + 1
                                self.player.upgrades[key] = self.player.upgrades.get(key,0) + 1
                                if key=='hp':
                                    self.player.maxhp += 20; self.player.hp = self.player.maxhp
                            elif key=='bomb':
                                self.player.bombs += 1
                            elif key=='heal':
                                self.player.hp = min(self.player.maxhp, self.player.hp + 40)
                    if e.key == pygame.K_ESCAPE:
                        self.state = 'play'
                if e.type == pygame.QUIT:
                    self.save(); pygame.quit(); sys.exit()

    def gameover_loop(self):
        self.screen.fill((6,8,10))
        t = self.big.render("GAME OVER", True, (255,160,160))
        s = self.font.render(f"Score: {int(self.player.score)}  Hi: {int(self.hiscore)}", True, (220,220,220))
        hint = self.font.render("Press Enter to return to Menu", True, (200,200,200))
        self.screen.blit(t, ((WIDTH-t.get_width())//2, 160))
        self.screen.blit(s, ((WIDTH-s.get_width())//2, 260))
        self.screen.blit(hint, ((WIDTH-hint.get_width())//2, 320))
        pygame.display.flip()
        for e in pygame.event.get():
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_RETURN:
                    self.state = 'menu'
            if e.type == pygame.QUIT:
                self.save(); pygame.quit(); sys.exit()

# ---------------- RUN ----------------
if __name__ == "__main__":
    g = Game()
    try:
        g.run()
    except Exception as ex:
        print("Error:", ex)
        pygame.quit()
        raise
