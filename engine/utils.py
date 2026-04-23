from config import SCREEN_SIZE

def world_to_screen(world_x, world_y, zoom, cam_offset):
    cx, cy = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2
    # Unified Formula: (World + Cam) * Zoom + ScreenCenter
    sx = cx + (world_x + cam_offset[0]) * zoom
    sy = cy + (world_y + cam_offset[1]) * zoom
    return sx, sy

def screen_to_world(screen_x, screen_y, zoom, cam_offset):
    cx, cy = SCREEN_SIZE[0] // 2, SCREEN_SIZE[1] // 2
    # Inverse Formula: (Screen - ScreenCenter) / Zoom - Camera
    wx = (screen_x - cx) / zoom - cam_offset[0]
    wy = (screen_y - cy) / zoom - cam_offset[1]
    return wx, wy