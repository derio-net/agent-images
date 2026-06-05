// Contract test for the patched RvfGridFSBucket GridFS shim.
//
// ruvocal's RVF backend ships an RvfGridFSBucket that mimics MongoDB's
// GridFSBucket so the Mongo-era chat-ui callers compile. The upstream shim is
// an incomplete mimic: openUploadStream returns a non-stream object,
// openDownloadStream is not a Readable, and find() is async with no next() —
// so uploadFile.ts (.once), downloadFile.ts (.on) and conversation.ts (.pipe)
// all crash. This test pins the contract the callers actually require:
//   - openUploadStream() -> Writable that accepts ArrayBuffer/Buffer/string,
//     emits "finish"/"error", exposes .id
//   - openDownloadStream() -> Readable emitting the stored bytes, or an
//     error-stream ("File not found") for a missing file (GridFS semantics)
//   - find() -> SYNC cursor with next() and toArray()
//   - base64 storage round-trips
//
// It mirrors the patched implementation (the patch lands in the vendored
// ruflo source at build time, which is not present in this repo), so it doubles
// as the executable spec for the upstream PR. Run: node --test ruflo-server/test/*.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { Readable, Writable } from "node:stream";

function makeBucket() {
	const files = new Map();
	return {
		openUploadStream(filename, options) {
			const id = "id-" + files.size;
			const chunks = [];
			const s = new Writable({
				objectMode: true,
				write(chunk, _enc, cb) {
					try {
						chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : Buffer.from(chunk));
						cb();
					} catch (e) {
						cb(e);
					}
				},
				final(cb) {
					try {
						files.set(id, {
							_id: id,
							filename,
							data: Buffer.concat(chunks).toString("base64"),
							metadata: options?.metadata ?? {},
						});
						cb();
					} catch (e) {
						cb(e);
					}
				},
			});
			s.id = id;
			return s;
		},
		openDownloadStream(id) {
			const f = files.get(String(id));
			if (!f) {
				// Match MongoDB GridFS (and the prior shim): a missing file is
				// an error, surfaced on the stream.
				const missing = new Readable({ read() {} });
				missing.destroy(new Error("File not found"));
				return missing;
			}
			return Readable.from([Buffer.from(f.data, "base64")]);
		},
		find(filter = {}) {
			const r = [...files.values()]
				.filter((d) => !filter.filename || d.filename === filter.filename)
				.map(({ data, ...m }) => m);
			let i = 0;
			return { next: async () => (i < r.length ? r[i++] : null), toArray: async () => r };
		},
	};
}

function readBack(stream) {
	return new Promise((resolve, reject) => {
		const cs = [];
		stream.on("data", (c) => cs.push(c));
		stream.on("error", reject);
		stream.on("end", () => resolve(Buffer.concat(cs)));
	});
}

test("upload accepts an ArrayBuffer (uploadFile.ts pattern) and emits finish", async () => {
	const b = makeBucket();
	const bytes = Buffer.from("hello image");
	const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength); // ArrayBuffer
	const up = b.openUploadStream("c-sha", { metadata: { conversation: "c" } });
	up.write(ab); // upstream casts ArrayBuffer to Buffer; a default Writable would throw here
	up.end();
	await new Promise((res, rej) => {
		up.once("finish", res);
		up.once("error", rej);
		setTimeout(() => rej(new Error("upload timed out")), 2000);
	});

	const meta = await b.find({ filename: "c-sha" }).next(); // sync cursor, no await on find
	assert.equal(meta.filename, "c-sha");

	const out = await readBack(b.openDownloadStream(meta._id)); // Readable, .on("data")
	assert.equal(out.toString(), "hello image");
});

test("pipe copy round-trips (conversation.ts fork-from-shared pattern)", async () => {
	const b = makeBucket();
	const src = b.openUploadStream("src");
	src.write(Buffer.from("payload"));
	src.end();
	await new Promise((r) => src.once("finish", r));
	const srcId = (await b.find({ filename: "src" }).next())._id;

	const dst = b.openUploadStream("dst");
	await new Promise((res, rej) => {
		b.openDownloadStream(srcId).on("error", rej).pipe(dst).on("error", rej).on("finish", res);
	});

	const dstId = (await b.find({ filename: "dst" }).next())._id;
	const out = await readBack(b.openDownloadStream(dstId));
	assert.equal(out.toString(), "payload");
});

test("openDownloadStream errors on a missing file (GridFS semantics; matches upstream rvf.spec.ts)", async () => {
	const b = makeBucket();
	// The upstream rvf.spec.ts "delete file" case asserts that downloading a
	// deleted/absent file rejects with "File not found". A naive empty-Readable
	// would silently resolve to [] and break that test.
	await assert.rejects(b.openDownloadStream("does-not-exist").toArray(), /File not found/);
});

test("find().toArray() returns metadata without the data blob", async () => {
	const b = makeBucket();
	const up = b.openUploadStream("only");
	up.write(Buffer.from("x"));
	up.end();
	await new Promise((r) => up.once("finish", r));
	const all = await b.find({}).toArray();
	assert.equal(all.length, 1);
	assert.equal(all[0].data, undefined); // data stripped from cursor results
	assert.equal(all[0].filename, "only");
});
