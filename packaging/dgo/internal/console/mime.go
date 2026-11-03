package console

import (
	"bytes"
	"compress/gzip"
	"compress/zlib"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// pyTypes is Python 3.12's mimetypes table (mimetypes._types_map_default), one type per line with
// its extensions. It is the WHOLE of what the console's Content-Type comes from: the image
// (python:3.12-slim) has no /etc/mime.types for Python to add, and the oracle switches off what
// Windows' registry or a desktop's mime.types would add. TestMimeTablesArePythons compares it with
// the interpreter's own.
const pyTypes = `text/javascript js mjs
application/json json
application/manifest+json webmanifest
application/msword doc dot wiz
application/n-quads nq
application/n-triples nt
application/octet-stream bin a dll exe o obj so
application/oda oda
application/pdf pdf
application/pkcs7-mime p7c
application/postscript ps ai eps
application/trig trig
application/vnd.apple.mpegurl m3u m3u8
application/vnd.ms-excel xls xlb
application/vnd.ms-powerpoint ppt pot ppa pps pwz
application/wasm wasm
application/x-bcpio bcpio
application/x-cpio cpio
application/x-csh csh
application/x-dvi dvi
application/x-gtar gtar
application/x-hdf hdf
application/x-hdf5 h5
application/x-latex latex
application/x-mif mif
application/x-netcdf cdf nc
application/x-pkcs12 p12 pfx
application/x-pn-realaudio ram
application/x-python-code pyc pyo
application/x-sh sh
application/x-shar shar
application/x-shockwave-flash swf
application/x-sv4cpio sv4cpio
application/x-sv4crc sv4crc
application/x-tar tar
application/x-tcl tcl
application/x-tex tex
application/x-texinfo texi texinfo
application/x-troff roff t tr
application/x-troff-man man
application/x-troff-me me
application/x-troff-ms ms
application/x-ustar ustar
application/x-wais-source src
application/xml xsl rdf wsdl xpdl
application/zip zip
audio/3gpp 3gp 3gpp
audio/3gpp2 3g2 3gpp2
audio/aac aac adts loas ass
audio/basic au snd
audio/mpeg mp3 mp2
audio/opus opus
audio/x-aiff aif aifc aiff
audio/x-pn-realaudio ra
audio/x-wav wav
image/avif avif
image/bmp bmp
image/gif gif
image/ief ief
image/jpeg jpg jpe jpeg
image/heic heic
image/heif heif
image/png png
image/svg+xml svg
image/tiff tiff tif
image/vnd.microsoft.icon ico
image/x-cmu-raster ras
image/x-portable-anymap pnm
image/x-portable-bitmap pbm
image/x-portable-graymap pgm
image/x-portable-pixmap ppm
image/x-rgb rgb
image/x-xbitmap xbm
image/x-xpixmap xpm
image/x-xwindowdump xwd
message/rfc822 eml mht mhtml nws
text/css css
text/csv csv
text/html html htm
text/markdown md markdown
text/n3 n3
text/plain txt bat c h ksh pl srt
text/richtext rtx
text/tab-separated-values tsv
text/vtt vtt
text/x-python py
text/x-rst rst
text/x-setext etx
text/x-sgml sgm sgml
text/x-vcard vcf
text/xml xml
video/mp4 mp4
video/mpeg mpeg m1v mpa mpe mpg
video/quicktime mov qt
video/webm webm
video/x-msvideo avi
video/x-sgi-movie movie`

// pyEncodings and pySuffixes are mimetypes' encodings_map (matched case-sensitively) and suffix_map
// (matched lowercased).
var (
	pyEncodings = map[string]string{".gz": "gzip", ".Z": "compress", ".bz2": "bzip2", ".xz": "xz", ".br": "br"}
	pySuffixes  = map[string]string{".svgz": ".svg.gz", ".tgz": ".tar.gz", ".taz": ".tar.gz", ".tz": ".tar.gz", ".tbz2": ".tar.bz2", ".txz": ".tar.xz"}
	pyTypeOf    = func() map[string]string {
		m := map[string]string{}
		for _, line := range strings.Split(pyTypes, "\n") {
			f := strings.Fields(line)
			for _, ext := range f[1:] {
				m["."+ext] = f[0]
			}
		}
		return m
	}()
)

// guessType is mimetypes.guess_type(name) for a name plain() lets through (no scheme, no drive):
// suffix_map rewrites first, then a case-sensitive encoding suffix comes off, then the type of the
// extension left, lowercased. "" when the table has none.
func guessType(name string) (typ, enc string) {
	base, ext := splitext(name)
	for {
		s, ok := pySuffixes[strings.ToLower(ext)]
		if !ok {
			break
		}
		base, ext = splitext(base + s)
	}
	if e, ok := pyEncodings[ext]; ok {
		enc = e
		_, ext = splitext(base)
	}
	return pyTypeOf[strings.ToLower(ext)], enc
}

// splitext is posixpath.splitext: the extension runs from the last dot — unless only dots precede
// it in the name, so ".bashrc" and "..js" have none.
func splitext(p string) (string, string) {
	sep := strings.LastIndexByte(p, '/')
	if dot := strings.LastIndexByte(p, '.'); dot > sep {
		for i := sep + 1; i < dot; i++ {
			if p[i] != '.' {
				return p[:dot], p[dot:]
			}
		}
	}
	return p, ""
}

// contentType is werkzeug's get_content_type(mimetype, "utf-8"): text, the +xml family and a few
// script and XML types carry the charset.
func contentType(mt string) string {
	switch mt {
	case "application/ecmascript", "application/javascript", "application/sql", "application/xml",
		"application/xml-dtd", "application/xml-external-parsed-entity":
		return mt + "; charset=utf-8"
	}
	if strings.HasPrefix(mt, "text/") || strings.HasSuffix(mt, "+xml") {
		return mt + "; charset=utf-8"
	}
	return mt
}

// ── flask-compress (1.25, the version the oracle runs) ────────────────────────────────────────────

// compressible is its COMPRESS_MIMETYPES default.
var compressible = func() map[string]bool {
	m := map[string]bool{}
	for _, t := range strings.Fields(`text/html text/css text/plain text/xml text/x-component
		text/javascript application/x-javascript application/javascript application/json
		application/manifest+json application/vnd.api+json application/xml application/xhtml+xml
		application/rss+xml application/atom+xml application/vnd.ms-fontobject application/x-font-ttf
		application/x-font-opentype application/x-font-truetype image/svg+xml image/x-icon
		image/vnd.microsoft.icon font/ttf font/eot font/otf font/opentype`) {
		m[t] = true
	}
	return m
}()

// minSize is COMPRESS_MIN_SIZE: a shorter body goes as it is.
const minSize = 500

// The codings flask-compress offers — COMPRESS_ALGORITHM for a buffered body, and
// COMPRESS_ALGORITHM_STREAMING (no gzip there) for a streamed one, which is what send_file answers
// — less zstd and br, which the standard library cannot write. choose() over these gives
// flask-compress's own answer whenever that answer is gzip, deflate or none: dropping a coding only
// changes a choice that WAS that coding (or `*` falling back to it). A client whose best offer is
// zstd or br gets the best of these instead — the same bytes once decoded, and for the shell's own
// files no larger (TestOffersOnlyFlaskCanWrite logs both sizes: app.js 48,568 B deflated here,
// 50,605 B as Flask's zstd).
var (
	bufferedEncodings = []string{"gzip", "deflate"}
	streamedEncodings = []string{"deflate"}
)

var (
	qDecimal  = regexp.MustCompile(`^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$`)
	qInfinity = regexp.MustCompile(`(?i)^[+-]?(?:inf|infinity)$`)
)

// choose is flask-compress's _choose_algorithm: the client's offers grouped by q, the highest group
// winning, the server's order inside it; `*` with q > 0 falls back to the server's first. Kept as
// it is: an unreadable q counts as 1.0, and q=0 is no refusal there. "" is identity. ok is false for
// a q Python's float() reads in ways this port does not (`nan`, digits with underscores).
func choose(server []string, header string) (string, bool) {
	fallback := false
	groups := map[float64]map[string]bool{}
	for _, part := range strings.Split(strings.ToLower(header), ",") {
		part = strings.Trim(part, " \t")
		algo, q := part, 1.0
		if strings.Contains(part, ";q=") {
			algo = strings.Trim(strings.SplitN(part, ";", 2)[0], " \t")
			s := strings.Trim(strings.Split(part, "=")[1], " \t")
			switch {
			case qDecimal.MatchString(s):
				q, _ = strconv.ParseFloat(s, 64)
			case qInfinity.MatchString(s):
				q = math.Inf(1)
				if s[0] == '-' {
					q = math.Inf(-1)
				}
			case strings.Contains(s, "_") || strings.Contains(s, "nan"):
				return "", false
			} // anything else is float()'s ValueError: q stays 1.0
		}
		member := ""
		switch {
		case algo == "*":
			fallback = fallback || q > 0
			continue
		case algo == "identity":
		case contains(server, algo):
			member = algo
		default:
			continue
		}
		if groups[q] == nil {
			groups[q] = map[string]bool{}
		}
		groups[q][member] = true
	}
	qs := make([]float64, 0, len(groups))
	for q := range groups {
		qs = append(qs, q)
	}
	sort.Sort(sort.Reverse(sort.Float64Slice(qs)))
	for _, q := range qs {
		g := groups[q]
		if len(g) == 1 {
			for m := range g {
				return m, true
			}
		}
		for _, a := range server {
			if g[a] {
				return a, true
			}
		}
	}
	if fallback {
		return server[0], true
	}
	return "", true
}

func contains(xs []string, x string) bool {
	for _, v := range xs {
		if v == x {
			return true
		}
	}
	return false
}

// compress is what flask-compress writes for a buffered body: gzip at COMPRESS_LEVEL 6, or zlib's
// deflate at its default level.
func compress(coding string, body []byte) []byte {
	var b bytes.Buffer
	if coding == "gzip" {
		zw, _ := gzip.NewWriterLevel(&b, 6)
		zw.Write(body)
		zw.Close()
	} else {
		zw := zlib.NewWriter(&b)
		zw.Write(body)
		zw.Close()
	}
	return b.Bytes()
}
