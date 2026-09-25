"""Numpad-modus: tikposities op het trackpad omzetten naar toetsen volgens een raster (Mobee-folie)."""


class NumpadGrid:
    def __init__(self, cfg):
        self.reload(cfg)

    def reload(self, cfg):
        np = cfg["numpad"]
        self.x0, self.x1 = np["x_mm"]
        self.y0, self.y1 = np["y_mm"]
        self.rows = np["rows"]
        # Tikken net buiten het raster (tot zover) tellen mee voor de buitenste rij/kolom: een vinger in een hoek
        # of tegen de rand (bijv. de numpad-schakelaar rechtsboven) meldt zijn zwaartepunt soms buiten het raster.
        self.margin = float(np.get("edge_margin_mm", 8.0))

    def cell(self, x_mm, y_mm):
        """(rij, kolom) of None als de tik buiten het raster (plus randmarge) valt."""
        m = self.margin
        if not self.rows or not (self.x0 - m <= x_mm <= self.x1 + m and self.y0 - m <= y_mm <= self.y1 + m):
            return None
        x_mm = min(self.x1, max(self.x0, x_mm))
        y_mm = min(self.y1, max(self.y0, y_mm))
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
