// ==========================================
// STATE
// ==========================================
let isLoginFilled = false;
let is2FAFilled = false;

// ==========================================
// REACT SAFE INPUT SETTER
// ==========================================
function setReactInputValue(input, value) {
    const nativeSetter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value"
    ).set;

    nativeSetter.call(input, value);

    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
}

// ==========================================
// FIND INPUTS
// ==========================================
function getEmailInput() {
    return document.querySelector('input[name="email"]');
}

function getPasswordInput() {
    return document.querySelector('input[name="password"]');
}

// ==========================================
// LOGIN AUTOFILL
// ==========================================
function autofillLogin() {

    if (!ACCOUNT) return;
    if (isLoginFilled) return;

    const email = getEmailInput();
    const pass = getPasswordInput();

    if (!email || !pass) return;
    if (email.value.length > 0) return;

    setReactInputValue(email, ACCOUNT.email);
    setReactInputValue(pass, ACCOUNT.password);

    isLoginFilled = true;
    console.log("Login Autofilled");
}

// ==========================================
// 2FA
// ==========================================
async function autofill2FA() {

    if (!ACCOUNT?.totpSecret) return;
    if (is2FAFilled) return;

    const otpInput =
        document.querySelector('input[autocomplete="one-time-code"]') ||
        document.querySelector('input[aria-label="6-digit authentication code"]');

    if (!otpInput) return;
    if (otpInput.value?.length === 6) return;

    try {

        const code = await window.generateTOTP(ACCOUNT.totpSecret);

        if (!code) {
            console.log("TOTP not generated");
            return;
        }

        setReactInputValue(otpInput, code);

        is2FAFilled = true;
        console.log("2FA Autofilled");

    } catch (err) {
        console.error("2FA autofill error:", err);
    }
}

// ==========================================
// WATCHER
// ==========================================
function startWatcher() {

    const interval = setInterval(() => {
        autofillLogin();
        autofill2FA();
    }, 800);

    setTimeout(() => clearInterval(interval), 60000);
}

startWatcher();
