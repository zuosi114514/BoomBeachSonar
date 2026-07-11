import sys
src = "K:/zzzzzzzzzzzz/edge_download/BoomBeachSonarAuto-main/main.py"
c = open(src, "r", encoding="utf-8-sig").read()
c = c.replace("\r\n", "\n")

# Find and replace the entire step 6 block
start = c.find("# === \u7b2c\u516d\u6b65")
end = c.find("\ndef _find_connected_components", start)
if end < 0:
    end = c.find("\nif __name__", start)
if end < 0:
    end = len(c)

old_block = c[start:end]
print("Found block:", repr(old_block[:60]))

new_block = '''# === \u7b2c\u516d\u6b65: \u5148\u6062\u590d\u7f51\u7edc + \u91cd\u542f\u6e38\u620f -> \u8fdb\u5165\u6d3b\u52a8 -> \u9010\u4e2a\u70b9\u51fb\u547d\u4e2d\u683c ===
    total_hits = sum(sum(row) for row in hit_map)
    if total_hits == 0:
        logger.info("\u6ca1\u6709\u547d\u4e2d\u683c\uff0c\u65e0\u9700\u70b9\u51fb")
        return
    logger.info("\u5171 %d \u4e2a\u547d\u4e2d\u683c\uff0c\u5148\u6062\u590d\u7f51\u7edc\u5e76\u91cd\u542f\u6e38\u620f...", total_hits)
    disable_weak_network()
    cleanup_reject_network()
    _restart_game_for_activity_retry()
    enter_activity()
    for row in range(grid_size):
        for col in range(grid_size):
            if hit_map[row][col] != 1:
                continue
            index = row * grid_size + col
            x, y = click_points[index]
            logger.warning("\u70b9\u51fb\u547d\u4e2d\u683c row=%d col=%d index=%d (%d, %d)", row, col, index, x, y)
            enter_activity()
            adb.click(x, y)
            adb.delay(0.5)
    logger.info("\u547d\u4e2d\u683c\u70b9\u51fb\u5b8c\u6210\uff0c\u5171 %d \u4e2a", total_hits)'''

c = c[:start] + new_block + c[end:]

open(src, "w", encoding="utf-8").write(c)
print("OK")