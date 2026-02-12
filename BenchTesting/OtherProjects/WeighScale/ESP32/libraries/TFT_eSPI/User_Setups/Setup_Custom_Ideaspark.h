
#define ST7789_DRIVER
#define TFT_WIDTH  135
#define TFT_HEIGHT 240
#define TFT_MOSI 23
#define TFT_SCLK 18
#define TFT_CS   15
#define TFT_DC    2
#define TFT_RST   4
#define TFT_BL    32
#define SPI_FREQUENCY 40000000

// Make sure these fonts are enabled:
#define LOAD_FONT2   // small text font (used for header)
#define LOAD_FONT4   // medium
#define LOAD_FONT6   // large
#define LOAD_FONT7   // large 7-seg numeric font for value
// Optional, only if you later want FreeFonts:
#define LOAD_GFXFF

