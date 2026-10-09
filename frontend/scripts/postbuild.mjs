// Postbuild: perbarui referensi aset hashed di ../warehouse_app/www/gudang.html
// dari hasil build (pengganti buildConfig plugin frappeui yang dibuang).
// Blok jinja {% for key in boot %} di www/gudang.html dipertahankan — hanya
// <script src> dan <link href> aset yang diganti.
import { readFileSync, writeFileSync, readdirSync } from 'node:fs'
import path from 'node:path'

const dist = path.resolve(process.cwd(), '../warehouse_app/public/gudang/assets')
const www = path.resolve(process.cwd(), '../warehouse_app/www/gudang.html')

const files = readdirSync(dist)
const js = files.find((f) => f.startsWith('index-') && f.endsWith('.js'))
const css = files.find((f) => f.startsWith('index-') && f.endsWith('.css'))
if (!js || !css) {
	console.error('postbuild: aset index-*.{js,css} tidak ditemukan di', dist)
	process.exit(1)
}

let html = readFileSync(www, 'utf8')
html = html
	.replace(/src="\/assets\/warehouse_app\/gudang\/assets\/index-[^"]+\.js"/, `src="/assets/warehouse_app/gudang/assets/${js}"`)
	.replace(/href="\/assets\/warehouse_app\/gudang\/assets\/index-[^"]+\.css"/, `href="/assets/warehouse_app/gudang/assets/${css}"`)
writeFileSync(www, html)
console.log('postbuild: www/gudang.html →', js, css)
