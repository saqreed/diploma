const assert = require('node:assert/strict')

async function enterValue(locator, value, keyboard = false) {
  const input = await locator.elementHandle()
  // Stock Firefox's BiDi fill can bypass React's value tracking. Native keyboard
  // input exercises the same events as a user, without changing application state.
  if (keyboard || process.env.QA_BROWSER_CHANNEL === 'moz-firefox') {
    await locator.click()
    await locator.press('ControlOrMeta+A')
    await locator.press('Backspace')
    if (value) await locator.pressSequentially(value)
    if (process.env.QA_BROWSER_CHANNEL === 'moz-firefox' && /[^\x00-\x7f]/.test(value)) {
      // BiDi implements non-US text through injected insertion. A normal edit
      // ensures React receives native input events for the completed text.
      await input.press('End')
      await input.press('Space')
      await input.press('Backspace')
    }
  } else {
    await locator.fill(value)
  }
  // A textarea's text can affect label matching in BiDi. Read the element that
  // received the keys rather than resolving the label again after typing.
  assert(await input.evaluate((element, expected) => element.value === expected, value), 'Entered value was not retained')
  await input.dispose()
}

module.exports = {enterValue}
