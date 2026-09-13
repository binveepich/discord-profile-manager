// =====================================================
// ROBUST TOTP GENERATOR
// =====================================================

const TOTP_TIME_STEP = 30;

let cachedKey = null;
let cachedSecret = null;


// =====================================================
// BASE32 SAFE DECODE
// =====================================================
function base32ToBytes(base32) {

    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

    base32 = (base32 || "")
        .toUpperCase()
        .replace(/=+$/g, "")
        .replace(/\s+/g, "");

    let bits = "";

    for (let char of base32) {
        const val = alphabet.indexOf(char);
        if (val === -1) continue;   // 🔥 skip invalid char
        bits += val.toString(2).padStart(5, "0");
    }

    const bytes = [];
    for (let i = 0; i + 8 <= bits.length; i += 8) {
        bytes.push(parseInt(bits.slice(i, i + 8), 2));
    }

    return new Uint8Array(bytes);
}


// =====================================================
// CACHE CRYPTO KEY
// =====================================================
async function getCryptoKey(secret) {

    if (!secret) throw new Error("Empty TOTP secret");

    if (cachedKey && cachedSecret === secret) {
        return cachedKey;
    }

    const keyBytes = base32ToBytes(secret);

    if (!keyBytes.length) {
        throw new Error("Invalid base32 secret");
    }

    cachedKey = await crypto.subtle.importKey(
        "raw",
        keyBytes,
        { name: "HMAC", hash: "SHA-1" },
        false,
        ["sign"]
    );

    cachedSecret = secret;

    return cachedKey;
}


// =====================================================
// TIME HELPERS
// =====================================================
function getTimeStep() {
    return Math.floor(Date.now() / 1000 / TOTP_TIME_STEP);
}

function secondsRemaining() {
    return TOTP_TIME_STEP - (Math.floor(Date.now() / 1000) % TOTP_TIME_STEP);
}


// =====================================================
// MAIN GENERATOR
// =====================================================
async function generateTOTP(secret) {

    try {

        if (!secret) return null;

        if (secondsRemaining() <= 2) {
            await new Promise(r => setTimeout(r, 2000));
        }

        const step = getTimeStep();
        const key = await getCryptoKey(secret);

        const buffer = new ArrayBuffer(8);
        const view = new DataView(buffer);

        view.setUint32(0, Math.floor(step / 0x100000000), false);
        view.setUint32(4, step % 0x100000000, false);

        const hmac = new Uint8Array(
            await crypto.subtle.sign("HMAC", key, buffer)
        );

        const offset = hmac[hmac.length - 1] & 0x0f;

        const binary =
            ((hmac[offset] & 0x7f) << 24) |
            (hmac[offset + 1] << 16) |
            (hmac[offset + 2] << 8) |
            (hmac[offset + 3]);

        return (binary % 1000000).toString().padStart(6, "0");

    } catch (err) {
        console.error("TOTP generation failed:", err);
        return null;
    }
}


// expose global (important for MV3 clarity)
window.generateTOTP = generateTOTP;