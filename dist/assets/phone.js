(() => {
  'use strict';
  function format(value) {
    let digits = value.replace(/\D/g, '');
    if (!digits) return '';
    if (digits[0] === '7' || digits[0] === '8') digits = digits.slice(1);
    // Keep an overlong number invalid rather than silently dropping digits.
    if (digits.length > 10) return value;
    let result = '+7';
    if (digits.length) result += ' (' + digits.slice(0, 3);
    if (digits.length >= 3) result += ')';
    if (digits.length > 3) result += ' ' + digits.slice(3, 6);
    if (digits.length > 6) result += '-' + digits.slice(6, 8);
    if (digits.length > 8) result += '-' + digits.slice(8, 10);
    return result;
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports = { format }; return; }
  document.querySelectorAll('[data-phone-only]').forEach(input => {
    input.addEventListener('input', () => {
      const wasAtEnd = input.selectionStart === input.value.length;
      const digitsBefore = input.value.slice(0, input.selectionStart).replace(/\D/g, '').length;
      input.value = format(input.value);
      if (wasAtEnd) return;
      let seen = 0, caret = 0;
      for (const char of input.value) { caret++; if (/\d/.test(char) && ++seen >= digitsBefore) break; }
      input.setSelectionRange(caret, caret);
    });
  });
})();
