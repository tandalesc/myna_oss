/* SPDX-License-Identifier: MIT */
/* vCard 3.0 (lib/vcard.h), written from RFC 2426 (vCard 3.0) and RFC 6350 (vCard 4.0). */
#include <stdint.h>

#include "lib/mem.h"
#include "lib/phonenum.h"
#include "lib/vcard.h"

#define FOLD 75                /* octets per line before a fold (RFC 2426 2.6, RFC 6350 3.2) */
#define LINE_MAX 640           /* a logical line kept for reading; longer ones (photos) are cut, then skipped */

static const char *const label_names[VCARD_LABELS] = { "Mobile", "Home", "Work", "Other" };
static const char *const label_types[VCARD_LABELS] = { "CELL", "HOME", "WORK", "VOICE" };

const char *vcard_label_name(unsigned label)
{
    return label < VCARD_LABELS ? label_names[label] : "Other";
}

/* ---- writing ---- */

struct out {
    char *p;
    unsigned n, max, col;      /* col: octets on the current line */
    int full;
};

static void raw(struct out *o, char c)
{
    if (o->n + 1 >= o->max) {
        o->full = 1;
        return;
    }
    o->p[o->n++] = c;
}

static void newline(struct out *o)
{
    raw(o, '\r');
    raw(o, '\n');
    o->col = 0;
}

/* one octet of a property line, folding before it when the line is full; a fold never falls inside a UTF-8
   character (continuation bytes 10xxxxxx are never the first octet of a new line) */
static void put(struct out *o, char c)
{
    if (o->col >= FOLD && ((uint8_t)c & 0xC0) != 0x80) {
        newline(o);
        raw(o, ' ');
        o->col = 1;
    }
    raw(o, c);
    o->col++;
}

static void puts_raw(struct out *o, const char *s)
{
    while (*s)
        put(o, *s++);
}

/* text value with the escapes of RFC 2426 4 / RFC 6350 3.4 */
static void puts_text(struct out *o, const char *s)
{
    for (; *s; s++) {
        switch (*s) {
        case '\\': put(o, '\\'); put(o, '\\'); break;
        case ';': put(o, '\\'); put(o, ';'); break;
        case ',': put(o, '\\'); put(o, ','); break;
        case '\n': put(o, '\\'); put(o, 'n'); break;
        case '\r': break;
        default: put(o, *s);
        }
    }
}

void vcard_display_name(const struct vcard_contact *c, char *out, unsigned max)
{
    unsigned n = 0;
    const char *parts[2] = { c->given, c->family };
    for (int i = 0; i < 2; i++) {
        if (!parts[i][0])
            continue;
        if (n && n + 1 < max)
            out[n++] = ' ';
        for (const char *s = parts[i]; *s && n + 1 < max; s++)
            out[n++] = *s;
    }
    if (!n && c->count)
        for (const char *s = c->numbers[0].number; *s && n + 1 < max; s++)
            out[n++] = *s;
    if (max)
        out[n < max ? n : max - 1] = 0;
}

int vcard_format(const struct vcard_contact *c, char *out, unsigned max)
{
    struct out o = { .p = out, .max = max };
    puts_raw(&o, "BEGIN:VCARD");
    newline(&o);
    puts_raw(&o, "VERSION:3.0");
    newline(&o);
    puts_raw(&o, "N:");
    puts_text(&o, c->family);
    put(&o, ';');
    puts_text(&o, c->given);
    puts_raw(&o, ";;;");
    newline(&o);
    char fn[2 * VCARD_NAME_MAX + 2];
    vcard_display_name(c, fn, sizeof fn);
    puts_raw(&o, "FN:");
    puts_text(&o, fn);
    newline(&o);
    for (unsigned i = 0; i < c->count && i < VCARD_NUMBERS; i++) {
        puts_raw(&o, "TEL;TYPE=");
        puts_raw(&o, label_types[c->numbers[i].label < VCARD_LABELS ? c->numbers[i].label : VCARD_OTHER]);
        put(&o, ':');
        puts_raw(&o, c->numbers[i].number);
        newline(&o);
    }
    if (c->note[0]) {
        puts_raw(&o, "NOTE:");
        puts_text(&o, c->note);
        newline(&o);
    }
    puts_raw(&o, "END:VCARD");
    newline(&o);
    if (o.full)
        return -1;
    out[o.n] = 0;
    return (int)o.n;
}

/* ---- reading ---- */

static char lower(char c)
{
    return c >= 'A' && c <= 'Z' ? (char)(c + 32) : c;
}

/* ASCII case-insensitive: does [s, s + n) equal the lower-case word w? */
static int is(const char *s, unsigned n, const char *w)
{
    unsigned i = 0;
    for (; i < n && w[i]; i++)
        if (lower(s[i]) != w[i])
            return 0;
    return i == n && !w[i];
}

/* copy at most max - 1 bytes, not ending inside a UTF-8 character */
static void copy_cut(char *dst, unsigned max, const char *src, unsigned n)
{
    if (n >= max) {
        n = max - 1;
        while (n && ((uint8_t)src[n] & 0xC0) == 0x80)
            n--;
    }
    memcpy(dst, src, n);
    dst[n] = 0;
}

static int hexval(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    c = lower(c);
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    return -1;
}

/* decode quoted-printable in place; returns the new length */
static unsigned unquote_qp(char *s, unsigned n)
{
    unsigned w = 0;
    for (unsigned r = 0; r < n; r++) {
        if (s[r] == '=' && r + 2 < n) {
            int hi = hexval(s[r + 1]), lo = hexval(s[r + 2]);
            if (hi >= 0 && lo >= 0) {
                s[w++] = (char)(hi << 4 | lo);
                r += 2;
                continue;
            }
        }
        s[w++] = s[r];
    }
    return w;
}

/* Split a text value at unescaped `sep` into component k (0-based), unescaping it into out. */
static void component(const char *v, unsigned n, char sep, unsigned k, char *out, unsigned max)
{
    char tmp[LINE_MAX];
    unsigned t = 0, index = 0;
    for (unsigned i = 0; i < n; i++) {
        char c = v[i];
        if (c == '\\' && i + 1 < n) {
            char e = v[++i];
            c = (e == 'n' || e == 'N') ? '\n' : e;
        } else if (c == sep) {
            if (index++ == k)
                break;
            continue;
        }
        if (index == k && t < sizeof tmp)
            tmp[t++] = c;
    }
    copy_cut(out, max, tmp, t);
}

/* label from the TYPE parameters: CELL wins, then WORK, then HOME */
static unsigned tel_label(const char *params, unsigned n)
{
    int cell = 0, work = 0, home = 0;
    unsigned i = 0;
    while (i < n) {
        /* words separated by ';', ',' or '=' (TYPE=CELL,VOICE / TYPE=cell;TYPE=pref / CELL;PREF / "cell,voice") */
        while (i < n && (params[i] == ';' || params[i] == ',' || params[i] == '=' || params[i] == '"'))
            i++;
        unsigned s = i;
        while (i < n && params[i] != ';' && params[i] != ',' && params[i] != '=' && params[i] != '"')
            i++;
        const char *w = params + s;
        unsigned l = i - s;
        if (is(w, l, "cell") || is(w, l, "mobile"))
            cell = 1;
        else if (is(w, l, "work"))
            work = 1;
        else if (is(w, l, "home"))
            home = 1;
    }
    return cell ? VCARD_MOBILE : work ? VCARD_WORK : home ? VCARD_HOME : VCARD_OTHER;
}

static int contains_qp(const char *params, unsigned n)
{
    for (unsigned i = 0; i + 16 <= n; i++)
        if (is(params + i, 16, "quoted-printable"))
            return 1;
    return 0;
}

struct reader {
    struct vcard_contact *c;
    int begun, ended;
    char fn[VCARD_NAME_MAX * 2];
};

static void property(struct reader *r, char *line, unsigned n)
{
    /* name part: up to the first ':' outside double quotes */
    unsigned colon = 0;
    int quoted = 0;
    while (colon < n && (line[colon] != ':' || quoted)) {
        if (line[colon] == '"')
            quoted = !quoted;
        colon++;
    }
    if (colon >= n)
        return;
    unsigned name_end = 0;
    while (name_end < colon && line[name_end] != ';')
        name_end++;
    /* drop a group: "item1.TEL" */
    unsigned name_start = 0;
    for (unsigned i = 0; i < name_end; i++)
        if (line[i] == '.')
            name_start = i + 1;
    const char *name = line + name_start;
    unsigned nl = name_end - name_start;
    const char *params = line + name_end;
    unsigned pl = colon - name_end;
    char *v = line + colon + 1;
    unsigned vl = n - colon - 1;

    if (is(name, nl, "begin")) {
        if (is(v, vl, "vcard"))
            r->begun = 1;
        return;
    }
    if (!r->begun || r->ended)
        return;
    if (is(name, nl, "end")) {
        r->ended = 1;
        return;
    }
    if (contains_qp(params, pl))
        vl = unquote_qp(v, vl);

    struct vcard_contact *c = r->c;
    if (is(name, nl, "n")) {
        component(v, vl, ';', 0, c->family, sizeof c->family);
        component(v, vl, ';', 1, c->given, sizeof c->given);
    } else if (is(name, nl, "fn")) {
        component(v, vl, '\0', 0, r->fn, sizeof r->fn);
    } else if (is(name, nl, "tel")) {
        if (c->count >= VCARD_NUMBERS)
            return;
        /* a 4.0 "tel:" URI: drop the scheme and any ";ext=" part */
        if (vl >= 4 && is(v, 4, "tel:")) {
            v += 4;
            vl -= 4;
            for (unsigned i = 0; i < vl; i++)
                if (v[i] == ';')
                    vl = i;
        }
        char written[VCARD_NUMBER_MAX];
        copy_cut(written, sizeof written, v, vl);
        struct vcard_number *num = &c->numbers[c->count];
        if (phonenum_normalize(written, num->number, sizeof num->number) < 0) {
            if (!written[0])
                return;
            copy_cut(num->number, sizeof num->number, written, (unsigned)strlen(written));
        }
        num->label = (uint8_t)tel_label(params, pl);
        c->count++;
    } else if (is(name, nl, "note")) {
        component(v, vl, '\0', 0, c->note, sizeof c->note);
    }
}

int vcard_parse(const char *in, unsigned len, struct vcard_contact *c)
{
    memset(c, 0, sizeof *c);
    struct reader r = { .c = c };
    char line[LINE_MAX];
    unsigned n = 0;
    unsigned i = 0;
    while (i <= len && !r.ended) {
        /* one physical line [i, e) */
        unsigned e = i;
        while (e < len && in[e] != '\r' && in[e] != '\n')
            e++;
        unsigned next = e;
        if (next < len && in[next] == '\r')
            next++;
        if (next < len && in[next] == '\n')
            next++;
        const char *p = in + i;
        unsigned pl = e - i;
        if (n && pl && (p[0] == ' ' || p[0] == '\t')) {
            /* a folded continuation: the space is not part of the value */
            p++;
            pl--;
        } else if (n && line[n - 1] == '=' && contains_qp(line, n)) {
            /* a quoted-printable soft line break: the '=' goes, the next line continues the value */
            n--;
        } else if (n) {
            property(&r, line, n);
            n = 0;
        }
        for (unsigned k = 0; k < pl && n < sizeof line; k++)
            line[n++] = p[k];
        if (e >= len) {
            if (n)
                property(&r, line, n);
            break;
        }
        i = next;
    }
    if (!r.begun)
        return -1;
    if (!c->given[0] && !c->family[0] && r.fn[0])
        copy_cut(c->given, sizeof c->given, r.fn, (unsigned)strlen(r.fn));
    if (!c->given[0] && !c->family[0] && !c->count)
        return -1;
    return 0;
}
