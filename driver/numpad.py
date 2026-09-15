"""Numpad-modus: tikposities op het trackpad omzetten naar toetsen volgens een raster (Mobee-folie)."""


class NumpadGrid:
    def __init__(self, cfg):
        self.reload(cfg)

    def reload(self, cfg):
        np = cfg["numpad"]
        self.x0, self.x1 = np["x_mm"]
        self.y0, self.y1 = np["y_mm"]
        self.rows = np["rows"]

    def cell(self, x_mm, y_mm):
        """(rij, kolom) of None als de tik buiten het raster valt."""
        if not self.rows or not (self.x0 <= x_mm <= self.x1 and self.y0 <= y_mm <= self.y1):
            return None
        nrows = len(self.rows)
        r = min(nrows - 1, int((y_mm - self.y0) / (self.y1 - self.y0) * nrows))
        ncols = len(self.rows[r])
        if ncols == 0:
            return None
        c = min(ncols - 1, int((x_mm - self.x0) / (self.x1 - self.x0) * ncols))
        return r, c

    def key_at(self, x_mm, y_mm):
        rc = self.cell(x_mm, y_mm)
        if rc is None:
            return None
        key = self.rows[rc[0]][rc[1]]
        return key if key and key.lower() not in ("none", "-", "") else None
