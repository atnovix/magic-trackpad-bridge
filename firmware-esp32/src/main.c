// TrackpadBridge — ESP32 als Bluetooth-HID-host voor de Apple Magic Trackpad 1 (A1339).  Firmware v4.
//
// Wat het doet:
//   1. Verbindt (en koppelt) met het trackpad op vast Bluetooth-adres. Na de eerste koppeling wachten we
//      bij voorkeur tot het trackpad zélf verbindt (dat doet het bij aanraken); zelf verbinden terwijl het
//      trackpad ook al bezig is gaf in v2 een vastgelopen stack ("rcvd ACL for unknown handle").
//   2. Houdt de link uit de Bluetooth-sniffmodus (het trackpad vraagt sniff met interval 18 slots = 11,25 ms;
//      daarin komen frames met 3+ vingers, die uit 2 basebandpakketten bestaan, niet meer door) en vraagt
//      de master-rol, zodat het bordje zelf het pollen bepaalt.
//   3. Zet het trackpad met feature-report 0xD7 = 0x01 in multitouch-modus (zelfde als Linux hid-magicmouse).
//   4. Decodeert de multitouch-reports (id 0x28: 4 bytes header + 9 bytes per vinger) en stuurt ze als
//      tekstregels over de console-UART (USB, 921600 baud) naar de laptop.
//   5. Luistert op dezelfde UART naar testcommando's (één letter), zodat linkinstellingen zonder herflashen
//      te proberen zijn. Stuur '?' voor de lijst.
//
// Regelformaat naar de laptop (elke regel eindigt op '\n'):
//   F <knop> <ts> <n> <id>,<x>,<y>,<state>,<major>,<minor>,<size>,<orient> ...   multitouch-frame
//   M <knoppen> <dx> <dy>                                                        muis-report (nog geen MT-modus)
//   B <procent>                                                                  accu
//   S <connected|disconnected|paired|mode ..|gap ..|stats ..|link ..>            status / diagnostiek
//   R <hex...>                                                                   onbekend report
// Alle andere regels zijn ESP-IDF-logging (beginnen met I/W/E (...)).
//
// We gebruiken bewust de lage Bluedroid-API (esp_bt_hid_host_*) en niet de esp_hid-component:
// die laatste filtert reports die niet in de HID-descriptor staan, en 0x28 staat daar niet in.

#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_err.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "esp_bt.h"
#include "esp_bt_main.h"
#include "esp_bt_device.h"
#include "esp_gap_bt_api.h"
#include "esp_hidh_api.h"
#include "driver/uart.h"

static const char *TAG = "bridge";

// --- Interne Bluedroid-API (stack/btm_api.h is niet publiek, maar de symbolen zitten in de bt-component) ---
// Signaturen gecontroleerd tegen ESP-IDF 6.0.1 (components/bt/host/bluedroid/stack/include/stack/btm_api.h).
#define HCI_ENABLE_MASTER_SLAVE_SWITCH 0x0001
#define HCI_ENABLE_HOLD_MODE           0x0002
#define HCI_ENABLE_SNIFF_MODE          0x0004
#define BTM_PM_MD_ACTIVE               0x00
#define BTM_PM_MD_SNIFF                0x02
#define BTM_PM_REG_SET                 1
#define BTM_PM_REG_NOTIF               2
#define BTM_PM_SET_ONLY_ID             0x80
#define BTM_ROLE_MASTER                0x00
#define BTM_ROLE_SLAVE                 0x01
#define BT_TRANSPORT_BR_EDR            1
typedef struct { uint16_t max, min, attempt, timeout; uint8_t mode; } btm_pm_pwr_md_t;      // tBTM_PM_PWR_MD
typedef void (btm_pm_status_cb_t)(uint8_t *bda, uint8_t status, uint16_t value, uint8_t hci_status);
typedef void (btm_cmpl_cb_t)(void *p1);
extern uint8_t BTM_SetLinkPolicy(uint8_t *remote_bda, uint16_t *settings);
extern void    BTM_SetDefaultLinkPolicy(uint16_t settings);
extern uint8_t BTM_PmRegister(uint8_t mask, uint8_t *p_pm_id, btm_pm_status_cb_t *p_cb);
extern uint8_t BTM_SetPowerMode(uint8_t pm_id, uint8_t *remote_bda, btm_pm_pwr_md_t *p_mode);
extern uint8_t BTM_SwitchRole(uint8_t *remote_bda, uint8_t new_role, btm_cmpl_cb_t *p_cb);
extern uint8_t BTM_GetRole(uint8_t *remote_bda, uint8_t *p_role);
extern uint8_t btm_remove_acl(uint8_t *bd_addr, uint8_t transport);
static uint8_t s_pm_id = BTM_PM_SET_ONLY_ID;

#define REPORT_TRACKPAD   0x28   // multitouch-frame
#define REPORT_DOUBLE     0xF7   // twee frames in één pakket (lengte-byte + frame, frame)
#define REPORT_MOUSE      0x02   // gewone muis (alleen vóór de modus-omschakeling)
#define REPORT_BATTERY    0x47   // feature: accupercentage 0..100

#define PKT_TYPES_ALL     0xCC18 // DM1/DH1/DM3/DH3/DM5/DH5, EDR toegestaan
#define PKT_TYPES_1SLOT   0x331E // alleen DH1/DM1 (basic rate), geen meerslots- en EDR-pakketten

// Apple Magic Trackpad 1 van de gebruiker (adres uit Windows Apparaatbeheer).
static esp_bd_addr_t s_trackpad_bda = { 0x60, 0xC5, 0x47, 0x81, 0xF2, 0x6F };

typedef enum { ST_IDLE, ST_CONNECTING, ST_CONNECTED } conn_state_t;

static volatile conn_state_t s_state = ST_IDLE;
static volatile bool     s_hidh_ready = false;
static volatile bool     s_acl_up = false;             // basebandlink naar het trackpad bestaat (GAP-events)
static volatile bool     s_bonded = false;             // koppelsleutel in NVS -> trackpad verbindt zelf
static volatile bool     s_mt_active = false;          // minstens één 0x28-frame gezien sinds verbinden
static volatile bool     s_want_active = true;         // sniff weigeren en actieve modus afdwingen ('a'/'s')
static volatile bool     s_want_master = true;         // master-rol vragen na verbinden ('m'/'l')
static volatile uint16_t s_pkt_types = PKT_TYPES_ALL;  // ACL-pakkettypes ('9'/'1')
static volatile uint8_t  s_link_mode = 0xFF;           // laatste gemelde HCI-modus (0 actief, 2 sniff)
static volatile uint16_t s_link_interval = 0;
static volatile int64_t  s_mouse_seen_at_us = 0;       // laatste muis-report (= nog geen multitouch-modus)
static volatile int64_t  s_connected_at_us = 0;
static volatile int64_t  s_last_mode_cmd_us = 0;
static volatile int64_t  s_next_connect_us = 0;        // niet eerder dan dit zelf verbinden
static volatile int64_t  s_last_frame_us = 0;
static volatile int      s_last_frame_n = 0;
static volatile uint32_t s_frames = 0;
static volatile uint32_t s_bytes = 0;
static volatile uint32_t s_dropped = 0;                // regels die niet in de UART-wachtrij pasten
static volatile uint32_t s_stalls = 0;                 // gaten > 150 ms terwijl er vingers op lagen
static volatile uint32_t s_hist[8];                    // frames per vingeraantal (0..6, 7 = 7+)
static volatile uint16_t s_max_len = 0;                // grootste 0x28-report tot nu toe

// Regels naar de laptop gaan via een wachtrij naar een aparte taak, zodat de Bluetooth-taak
// nooit hoeft te wachten op de UART.
#define BRIDGE_LINE_MAX 400
typedef struct { uint16_t len; char text[BRIDGE_LINE_MAX]; } line_t;
static QueueHandle_t s_line_q;

static void tx_task(void *arg)
{
    static line_t l;
    for (;;) {
        if (xQueueReceive(s_line_q, &l, portMAX_DELAY) == pdTRUE) {
            fwrite(l.text, 1, l.len, stdout);
            fflush(stdout);
        }
    }
}

static void queue_line(const char *text, int len)
{
    line_t l;
    if (len <= 0) return;
    if (len > BRIDGE_LINE_MAX - 1) len = BRIDGE_LINE_MAX - 1;
    memcpy(l.text, text, len);
    l.text[len] = '\n';
    l.len = len + 1;
    if (xQueueSend(s_line_q, &l, 0) != pdTRUE) s_dropped++;
}

static void status_line(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void status_line(const char *fmt, ...)
{
    char buf[200];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    if (n >= (int)sizeof buf) n = sizeof buf - 1;
    queue_line(buf, n);
}

static const char *bda_str(const esp_bd_addr_t bda, char *buf)
{
    sprintf(buf, "%02X:%02X:%02X:%02X:%02X:%02X", bda[0], bda[1], bda[2], bda[3], bda[4], bda[5]);
    return buf;
}

static bool is_trackpad(const uint8_t *bda) { return memcmp(bda, s_trackpad_bda, 6) == 0; }

// ---------------------------------------------------------------------------
// Multitouch-frame decoderen (formaat uit Linux drivers/hid/hid-magicmouse.c)
// ---------------------------------------------------------------------------
static void emit_frame(const uint8_t *d, uint16_t len)
{
    if (len < 4 || ((len - 4) % 9) != 0) {
        ESP_LOGW(TAG, "0x28-report met onverwachte lengte %u", len);
        return;
    }
    int n = (len - 4) / 9;
    uint32_t ts = (uint32_t)(d[1] >> 6) | ((uint32_t)d[2] << 2) | ((uint32_t)d[3] << 10);
    int btn = d[1] & 0x01;

    // Stall-diagnostiek: lagen er bij het vorige frame vingers op en zit er nu een gat van > 150 ms
    // tussen, dan zijn er frames verloren gegaan in de link (het trackpad zendt ~100 Hz).
    int64_t now = esp_timer_get_time();
    if (s_last_frame_us != 0 && s_last_frame_n > 0 && now - s_last_frame_us > 150000LL) {
        s_stalls++;
        status_line("S gap n=%d ms=%" PRId64 " now_n=%d", s_last_frame_n, (now - s_last_frame_us) / 1000, n);
    }
    s_last_frame_us = now;
    s_last_frame_n = n;

    s_mt_active = true;
    s_frames++;
    s_hist[n < 7 ? n : 7]++;
    if (len > s_max_len) s_max_len = len;

    char line[BRIDGE_LINE_MAX];
    int pos = snprintf(line, sizeof line, "F %d %" PRIu32 " %d", btn, ts, n);
    for (int i = 0; i < n; i++) {
        const uint8_t *t = d + 4 + i * 9;
        int id     = ((t[7] << 2) | (t[6] >> 6)) & 0x0F;
        int32_t x  = (int32_t)(((uint32_t)t[1] << 27) | ((uint32_t)t[0] << 19)) >> 19;
        int32_t y  = -((int32_t)(((uint32_t)t[3] << 30) | ((uint32_t)t[2] << 22) | ((uint32_t)t[1] << 14)) >> 19);
        int size   = t[6] & 0x3F;
        int orient = (t[7] >> 2) - 32;
        int major  = t[4];
        int minor  = t[5];
        int state  = (t[8] & 0xF0) >> 4;     // 0 = los, 3 = start, 4 = sleep/vast
        int wrote = snprintf(line + pos, sizeof line - pos, " %d,%" PRId32 ",%" PRId32 ",%d,%d,%d,%d,%d",
                             id, x, y, state, major, minor, size, orient);
        if (wrote < 0 || pos + wrote >= (int)sizeof line - 1) break;
        pos += wrote;
    }
    queue_line(line, pos);
}

static void handle_input(const uint8_t *d, uint16_t len)
{
    if (len == 0) return;
    switch (d[0]) {
    case REPORT_TRACKPAD:
        emit_frame(d, len);
        break;
    case REPORT_DOUBLE:
        // d[1] = lengte van het eerste frame; daarna volgt het tweede frame.
        if (len >= 2 && d[1] > 0 && (uint16_t)(2 + d[1]) <= len) {
            handle_input(d + 2, d[1]);
            handle_input(d + 2 + d[1], len - 2 - d[1]);
        }
        break;
    case REPORT_MOUSE: {
        s_mouse_seen_at_us = esp_timer_get_time();
        if (len >= 4) status_line("M %u %d %d", d[1], (int8_t)d[2], (int8_t)d[3]);
        break;
    }
    default: {
        char hex[3 * 32 + 2]; int pos = sprintf(hex, "R");
        for (int i = 0; i < len && i < 32; i++) pos += sprintf(hex + pos, " %02X", d[i]);
        queue_line(hex, pos);
        break;
    }
    }
}

// ---------------------------------------------------------------------------
// Commando's naar het trackpad / linkinstellingen
// ---------------------------------------------------------------------------
static void send_mt_mode(void)
{
    uint8_t cmd[2] = { 0xD7, 0x01 };
    esp_err_t r = esp_bt_hid_host_set_report(s_trackpad_bda, ESP_HIDH_REPORT_TYPE_FEATURE, cmd, sizeof cmd);
    ESP_LOGI(TAG, "multitouch-modus aanzetten (feature 0xD7=1): %s", esp_err_to_name(r));
    s_last_mode_cmd_us = esp_timer_get_time();
}

// Link actief houden: sniff/hold/park uit de link policy (dan wijst de controller het sniff-verzoek van
// het trackpad af) en zelf actieve modus eisen (dan wint dat van Bluedroids eigen power manager:
// btm_pm_get_set_mode geeft ACTIVE voorrang zodra één geregistreerde partij dat vraagt).
static void apply_power_policy(const char *why)
{
    if (!s_acl_up) return;
    uint16_t policy = s_want_active ? HCI_ENABLE_MASTER_SLAVE_SWITCH
                                    : (HCI_ENABLE_MASTER_SLAVE_SWITCH | HCI_ENABLE_SNIFF_MODE);
    uint8_t r1 = BTM_SetLinkPolicy(s_trackpad_bda, &policy);
    btm_pm_pwr_md_t md = { 0 };
    uint8_t r2;
    if (s_want_active) {
        md.mode = BTM_PM_MD_ACTIVE;
        r2 = BTM_SetPowerMode(s_pm_id, s_trackpad_bda, &md);
    } else {
        // sniff weer toestaan: ons eigen verzoek op sniff met ruime grenzen, zodat het trackpad zijn zin krijgt
        md.mode = BTM_PM_MD_SNIFF; md.max = 800; md.min = 6; md.attempt = 4; md.timeout = 1;
        r2 = BTM_SetPowerMode(s_pm_id, s_trackpad_bda, &md);
    }
    status_line("S link policy=0x%04x active=%d r=%u/%u (%s)", policy, s_want_active, r1, r2, why);
}

static void role_cb(void *p) { (void)p; }

static void apply_role(const char *why)
{
    if (!s_acl_up) return;
    uint8_t cur = 0xFF;
    BTM_GetRole(s_trackpad_bda, &cur);
    uint8_t want = s_want_master ? BTM_ROLE_MASTER : BTM_ROLE_SLAVE;
    uint8_t r = 0;
    if (cur != want) r = BTM_SwitchRole(s_trackpad_bda, want, role_cb);
    status_line("S role now=%s want=%s r=%u (%s)", cur == BTM_ROLE_MASTER ? "master" : cur == BTM_ROLE_SLAVE ? "slave" : "?",
                s_want_master ? "master" : "slave", r, why);
}

static void apply_pkt_types(const char *why)
{
    if (!s_acl_up) return;
    esp_err_t r = esp_bt_gap_set_acl_pkt_types(s_trackpad_bda, s_pkt_types);
    status_line("S pkt types=0x%04x r=%d (%s)", s_pkt_types, (int)r, why);
}

static void pm_status_cb(uint8_t *bda, uint8_t status, uint16_t value, uint8_t hci_status)
{
    (void)bda;
    ESP_LOGD(TAG, "PM status %u value %u hci %u", status, value, hci_status);
}

static void request_battery(void)
{
    esp_err_t r = esp_bt_hid_host_get_report(s_trackpad_bda, ESP_HIDH_REPORT_TYPE_FEATURE, REPORT_BATTERY, 0);
    if (r != ESP_OK) ESP_LOGW(TAG, "accu opvragen mislukt: %s", esp_err_to_name(r));
}

static const char *role_name(uint8_t role) { return role == 0 ? "master" : role == 1 ? "slave" : "?"; }

static void print_link_state(void)
{
    uint8_t role = 0xFF;
    if (s_acl_up) BTM_GetRole(s_trackpad_bda, &role);
    status_line("S state conn=%d acl=%d bonded=%d role=%s mode=%u intv=%u active=%d master=%d pkt=0x%04x mt=%d",
                (int)s_state, s_acl_up, s_bonded, role_name(role),
                s_link_mode, s_link_interval, s_want_active, s_want_master, s_pkt_types, s_mt_active);
}

// ---------------------------------------------------------------------------
// Bluetooth GAP (koppelen, ACL-status, moduswissels)
// ---------------------------------------------------------------------------
static void gap_cb(esp_bt_gap_cb_event_t event, esp_bt_gap_cb_param_t *param)
{
    char buf[18];
    switch (event) {
    case ESP_BT_GAP_AUTH_CMPL_EVT:
        if (param->auth_cmpl.stat == ESP_BT_STATUS_SUCCESS) {
            ESP_LOGI(TAG, "gekoppeld met %s (%s)", (const char *)param->auth_cmpl.device_name, bda_str(param->auth_cmpl.bda, buf));
            s_bonded = true;
            queue_line("S paired", 8);
        } else {
            ESP_LOGW(TAG, "koppelen mislukt, status %d", param->auth_cmpl.stat);
        }
        break;
    case ESP_BT_GAP_PIN_REQ_EVT: {
        ESP_LOGI(TAG, "PIN gevraagd door %s (16 cijfers: %d) -> 0000", bda_str(param->pin_req.bda, buf), param->pin_req.min_16_digit);
        esp_bt_pin_code_t pin = { '0', '0', '0', '0' };
        esp_bt_gap_pin_reply(param->pin_req.bda, true, 4, pin);
        break;
    }
    case ESP_BT_GAP_CFM_REQ_EVT:
        ESP_LOGI(TAG, "SSP-bevestiging gevraagd (%" PRIu32 ") -> ja", param->cfm_req.num_val);
        esp_bt_gap_ssp_confirm_reply(param->cfm_req.bda, true);
        break;
    case ESP_BT_GAP_KEY_NOTIF_EVT:
        ESP_LOGI(TAG, "passkey-notificatie %" PRIu32, param->key_notif.passkey);
        break;
    case ESP_BT_GAP_KEY_REQ_EVT:
        ESP_LOGW(TAG, "passkey-invoer gevraagd; niet ondersteund");
        break;
    case ESP_BT_GAP_ACL_CONN_CMPL_STAT_EVT:
        ESP_LOGI(TAG, "ACL verbonden met %s (status %d, handle %u)", bda_str(param->acl_conn_cmpl_stat.bda, buf),
                 param->acl_conn_cmpl_stat.stat, param->acl_conn_cmpl_stat.handle);
        if (is_trackpad(param->acl_conn_cmpl_stat.bda) && param->acl_conn_cmpl_stat.stat == ESP_BT_STATUS_SUCCESS) {
            s_acl_up = true;
            s_link_mode = 0; s_link_interval = 0;
            status_line("S acl up");
            // Meteen na het opkomen van de basebandlink: policy en pakkettypes, vóór het trackpad sniff vraagt.
            apply_power_policy("acl up");
            apply_pkt_types("acl up");
        }
        break;
    case ESP_BT_GAP_ACL_DISCONN_CMPL_STAT_EVT:
        ESP_LOGI(TAG, "ACL verbroken met %s (reden 0x%x)", bda_str(param->acl_disconn_cmpl_stat.bda, buf), param->acl_disconn_cmpl_stat.reason);
        if (is_trackpad(param->acl_disconn_cmpl_stat.bda)) {
            s_acl_up = false;
            s_link_mode = 0xFF;
            status_line("S acl down reason=0x%x", param->acl_disconn_cmpl_stat.reason);
        }
        break;
    case ESP_BT_GAP_MODE_CHG_EVT:
        s_link_mode = param->mode_chg.mode;
        s_link_interval = param->mode_chg.interval;
        status_line("S mode %u intv=%u", param->mode_chg.mode, param->mode_chg.interval);
        if (param->mode_chg.mode != ESP_BT_PM_MD_ACTIVE && s_want_active) apply_power_policy("na moduswissel");
        break;
    default:
        ESP_LOGI(TAG, "GAP-event %d", event);
        break;
    }
}

// ---------------------------------------------------------------------------
// HID-host events
// ---------------------------------------------------------------------------
static void hidh_cb(esp_hidh_cb_event_t event, esp_hidh_cb_param_t *param)
{
    char buf[18];
    switch (event) {
    case ESP_HIDH_INIT_EVT:
        ESP_LOGI(TAG, "HID-host geinitialiseerd (status %d)", param->init.status);
        s_hidh_ready = (param->init.status == ESP_HIDH_OK);
        break;
    case ESP_HIDH_OPEN_EVT:
        if (param->open.conn_status == ESP_HIDH_CONN_STATE_CONNECTING) break;
        if (param->open.status == ESP_HIDH_OK && param->open.conn_status == ESP_HIDH_CONN_STATE_CONNECTED) {
            ESP_LOGI(TAG, "trackpad %s verbonden (handle %d, %s)", bda_str(param->open.bd_addr, buf), param->open.handle,
                     param->open.is_orig ? "door ons gestart" : "door trackpad gestart");
            s_state = ST_CONNECTED;
            s_mt_active = false;
            s_mouse_seen_at_us = 0;
            s_connected_at_us = esp_timer_get_time();
            s_last_mode_cmd_us = 0;
            s_last_frame_us = 0;
            s_last_frame_n = 0;
            s_frames = 0;
            s_acl_up = true;   // zeker weten (ACL-event kan vóór onze registratie gevallen zijn)
            status_line("S connected orig=%d", param->open.is_orig);
            apply_power_policy("bij verbinden");
            apply_pkt_types("bij verbinden");
            apply_role("bij verbinden");
        } else {
            ESP_LOGW(TAG, "verbinden mislukt (status %d, conn_status %d)", param->open.status, param->open.conn_status);
            s_state = ST_IDLE;
            s_next_connect_us = esp_timer_get_time() + 15 * 1000000LL;
        }
        break;
    case ESP_HIDH_CLOSE_EVT:
    case ESP_HIDH_VC_UNPLUG_EVT:
        if (event == ESP_HIDH_CLOSE_EVT)
            ESP_LOGI(TAG, "verbinding gesloten (status %d, reden %d), %" PRIu32 " frames ontvangen", param->close.status, param->close.reason, s_frames);
        else
            ESP_LOGW(TAG, "virtual cable unplug");
        s_state = ST_IDLE;
        s_mt_active = false;
        s_next_connect_us = esp_timer_get_time() + 15 * 1000000LL;   // trackpad verbindt meestal zelf opnieuw
        if (s_acl_up) {
            // HID dicht maar de basebandlink staat nog: dat is de v2-race (ons eigen verbindverzoek liep nog
            // toen het trackpad al verbond). Zonder ingrijpen blijft de stack ~20 s hangen tot de supervision-
            // timeout; de ACL zelf afbreken laat het trackpad snel opnieuw verbinden.
            status_line("S disconnected acl-still-up -> acl afbreken");
            btm_remove_acl(s_trackpad_bda, BT_TRANSPORT_BR_EDR);
        } else {
            queue_line("S disconnected", 14);
        }
        break;
    case ESP_HIDH_GET_DSCP_EVT:
        ESP_LOGI(TAG, "HID-descriptor: VID %04X PID %04X versie %04X, %u bytes, toegevoegd=%d",
                 param->dscp.vendor_id, param->dscp.product_id, param->dscp.version, param->dscp.dl_len, param->dscp.added);
        break;
    case ESP_HIDH_ADD_DEV_EVT:
        ESP_LOGI(TAG, "apparaat toegevoegd (status %d, handle %d)", param->add_dev.status, param->add_dev.handle);
        break;
    case ESP_HIDH_SET_RPT_EVT:
        ESP_LOGI(TAG, "SET_REPORT antwoord: status %d", param->set_rpt.status);
        break;
    case ESP_HIDH_GET_RPT_EVT:
        if (param->get_rpt.status == ESP_HIDH_OK && param->get_rpt.len >= 1) {
            const uint8_t *d = param->get_rpt.data;
            int pct = (param->get_rpt.len >= 2 && d[0] == REPORT_BATTERY) ? d[1] : d[0];
            status_line("B %d", pct);
        } else {
            ESP_LOGW(TAG, "GET_REPORT mislukt (status %d)", param->get_rpt.status);
        }
        break;
    case ESP_HIDH_DATA_IND_EVT:
        s_bytes += param->data_ind.len;
        handle_input(param->data_ind.data, param->data_ind.len);
        break;
    default:
        ESP_LOGD(TAG, "HIDH-event %d", event);
        break;
    }
}

// ---------------------------------------------------------------------------
// Testcommando's van de laptop (één letter op de console-UART)
// ---------------------------------------------------------------------------
static void print_help(void)
{
    static const char *lines[] = {
        "S help  ?  toestand tonen",
        "S help  a  sniff weigeren, link actief houden (standaard)",
        "S help  s  sniff toestaan (test)",
        "S help  m  master-rol vragen (standaard)   l  slave-rol",
        "S help  9  alle ACL-pakkettypes (standaard)   1  alleen 1-slot DM1/DH1",
        "S help  c  nu zelf verbinden   d  HID-verbinding verbreken   x  ACL afbreken",
        "S help  t  multitouch-commando (D7 01) opnieuw sturen   b  accu opvragen",
        "S help  z  tellers op nul",
    };
    for (size_t i = 0; i < sizeof lines / sizeof lines[0]; i++) queue_line(lines[i], strlen(lines[i]));
}

static void handle_command(char c)
{
    switch (c) {
    case '?': case 'h': print_help(); print_link_state(); break;
    case 'a': s_want_active = true;  apply_power_policy("cmd a"); break;
    case 's': s_want_active = false; apply_power_policy("cmd s"); break;
    case 'm': s_want_master = true;  apply_role("cmd m"); break;
    case 'l': s_want_master = false; apply_role("cmd l"); break;
    case '9': s_pkt_types = PKT_TYPES_ALL;   apply_pkt_types("cmd 9"); break;
    case '1': s_pkt_types = PKT_TYPES_1SLOT; apply_pkt_types("cmd 1"); break;
    case 'c': s_next_connect_us = 0; status_line("S cmd verbinden"); break;
    case 'd': status_line("S cmd disconnect r=%d", (int)esp_bt_hid_host_disconnect(s_trackpad_bda)); break;
    case 'x': status_line("S cmd acl afbreken r=%u", btm_remove_acl(s_trackpad_bda, BT_TRANSPORT_BR_EDR)); break;
    case 't': if (s_state == ST_CONNECTED) send_mt_mode(); break;
    case 'b': if (s_state == ST_CONNECTED) request_battery(); break;
    case 'z': s_frames = s_bytes = s_dropped = s_stalls = 0; s_max_len = 0; memset((void *)s_hist, 0, sizeof s_hist); status_line("S tellers gewist"); break;
    case '\r': case '\n': case ' ': break;
    default: status_line("S onbekend commando '%c' (? = help)", c); break;
    }
}

static void rx_task(void *arg)
{
    uint8_t b;
    for (;;) {
        if (uart_read_bytes(UART_NUM_0, &b, 1, portMAX_DELAY) == 1) handle_command((char)b);
    }
}

// ---------------------------------------------------------------------------
// Toezichthouder: verbinden, modus-omschakeling, accu, statistiek
// ---------------------------------------------------------------------------
static void supervisor_task(void *arg)
{
    int64_t last_connect_try = 0;
    int64_t last_battery = 0;
    int64_t last_stats = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(250));
        if (!s_hidh_ready) continue;
        int64_t now = esp_timer_get_time();

        switch (s_state) {
        case ST_IDLE:
            // Zelf verbinden alleen als er geen basebandlink is (anders "Conn Exists" / dubbele ACL-poging)
            // en pas na de wachttijd: een gekoppeld trackpad verbindt bij aanraken zelf, en dat is de
            // veilige route. Commando 'c' zet de wachttijd op nul.
            if (!s_acl_up && now - last_connect_try > 5 * 1000000LL && now >= s_next_connect_us) {
                last_connect_try = now;
                s_state = ST_CONNECTING;
                ESP_LOGI(TAG, "verbinden met trackpad...");
                if (esp_bt_hid_host_connect(s_trackpad_bda) != ESP_OK) {
                    s_state = ST_IDLE;
                    s_next_connect_us = now + 15 * 1000000LL;
                }
            }
            break;
        case ST_CONNECTING:
            if (now - last_connect_try > 25 * 1000000LL) {
                ESP_LOGW(TAG, "verbindpoging duurt te lang, opnieuw");
                s_state = ST_IDLE;
                s_next_connect_us = now + 15 * 1000000LL;
            }
            break;
        case ST_CONNECTED: {
            int64_t since_conn = now - s_connected_at_us;
            int64_t since_cmd  = now - s_last_mode_cmd_us;
            bool mouse_after_cmd = s_last_mode_cmd_us != 0 && s_mouse_seen_at_us > s_last_mode_cmd_us + 700000LL;
            bool need_cmd = (s_last_mode_cmd_us == 0 && since_conn > 300000LL)                    // eerste keer, 0,3 s na verbinden
                          || (mouse_after_cmd && since_cmd > 2 * 1000000LL);                       // nog steeds in muismodus
            if (need_cmd) send_mt_mode();
            if (now - last_stats > 5 * 1000000LL) {
                last_stats = now;
                uint8_t role = 0xFF;
                if (s_acl_up) BTM_GetRole(s_trackpad_bda, &role);
                status_line("S stats frames=%" PRIu32 " n1=%" PRIu32 " n2=%" PRIu32 " n3=%" PRIu32 " n4=%" PRIu32 " n5=%" PRIu32 " n6+=%" PRIu32
                            " maxlen=%u bytes=%" PRIu32 " stalls=%" PRIu32 " drop=%" PRIu32 " mode=%u intv=%u role=%s heap=%" PRIu32,
                            s_frames, s_hist[1], s_hist[2], s_hist[3], s_hist[4], s_hist[5], s_hist[6] + s_hist[7], s_max_len, s_bytes,
                            s_stalls, s_dropped, s_link_mode, s_link_interval, role_name(role), esp_get_free_heap_size());
            }
            if ((last_battery == 0 && since_conn > 2 * 1000000LL) || (last_battery != 0 && now - last_battery > 600 * 1000000LL)) {
                last_battery = now;
                request_battery();
            }
            break;
        }
        }
        if (s_state != ST_CONNECTED) last_battery = 0;
    }
}

void app_main(void)
{
    s_line_q = xQueueCreate(32, sizeof(line_t));
    xTaskCreate(tx_task, "uart_tx", 3072, NULL, 4, NULL);

    // Console-UART ook lezen (commando's van de laptop). Schrijven blijft via stdout lopen.
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 256, 0, 0, NULL, 0));
    xTaskCreate(rx_task, "uart_rx", 3072, NULL, 3, NULL);

    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    ret = esp_bt_controller_mem_release(ESP_BT_MODE_BLE);
    if (ret != ESP_OK) ESP_LOGW(TAG, "BLE-geheugen vrijgeven: %s", esp_err_to_name(ret));

    esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_bt_controller_init(&bt_cfg));
    ESP_ERROR_CHECK(esp_bt_controller_enable(ESP_BT_MODE_CLASSIC_BT));

    esp_bluedroid_config_t bd_cfg = BT_BLUEDROID_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_bluedroid_init_with_cfg(&bd_cfg));
    ESP_ERROR_CHECK(esp_bluedroid_enable());

    ESP_ERROR_CHECK(esp_bt_gap_register_callback(gap_cb));
    esp_bt_gap_set_device_name("TrackpadBridge");

    // Standaard link policy zonder sniff/hold/park; eigen power-manager-registratie zodat onze
    // "actief"-eis blijft staan als Bluedroid zelf sniff wil (lukt registreren niet, dan per keer forceren).
    BTM_SetDefaultLinkPolicy(HCI_ENABLE_MASTER_SLAVE_SWITCH);
    uint8_t pm_id = 0;
    if (BTM_PmRegister(BTM_PM_REG_SET | BTM_PM_REG_NOTIF, &pm_id, pm_status_cb) == 0) {
        s_pm_id = pm_id;
        ESP_LOGI(TAG, "power-manager geregistreerd als id %u", pm_id);
    } else {
        ESP_LOGW(TAG, "power-manager registreren mislukt; val terug op eenmalige set");
    }

    // Secure Simple Pairing: wij hebben een "display + ja/nee"; het trackpad heeft niets -> Just Works.
    esp_bt_io_cap_t iocap = ESP_BT_IO_CAP_IO;
    esp_bt_gap_set_security_param(ESP_BT_SP_IOCAP_MODE, &iocap, sizeof(uint8_t));
    // Terugval voor legacy-koppeling: PIN via PIN_REQ-event beantwoorden (0000).
    esp_bt_pin_code_t pin = { 0 };
    esp_bt_gap_set_pin(ESP_BT_PIN_TYPE_VARIABLE, 0, pin);

    // Verbindbaar (zodat het trackpad na de slaapstand zelf terug kan komen), niet zichtbaar voor anderen.
    esp_bt_gap_set_scan_mode(ESP_BT_CONNECTABLE, ESP_BT_NON_DISCOVERABLE);

    // Al gekoppeld? Dan het trackpad eerst 30 s de kans geven zelf te verbinden (raak het aan).
    int bonds = esp_bt_gap_get_bond_device_num();
    s_bonded = bonds > 0;
    s_next_connect_us = esp_timer_get_time() + (s_bonded ? 30 : 3) * 1000000LL;
    ESP_LOGI(TAG, "koppelsleutels in NVS: %d -> %s", bonds,
             s_bonded ? "wachten op het trackpad (raak het aan), anders na 30 s zelf verbinden" : "zelf verbinden (koppelmodus op het trackpad aanzetten)");

    ESP_ERROR_CHECK(esp_bt_hid_host_register_callback(hidh_cb));
    ESP_ERROR_CHECK(esp_bt_hid_host_init());

    xTaskCreate(supervisor_task, "supervisor", 4096, NULL, 5, NULL);
    ESP_LOGI(TAG, "TrackpadBridge v4 gestart; eigen adres %s; '?' voor commando's", bda_str(esp_bt_dev_get_address(), (char[18]){0}));
    print_help();
}
