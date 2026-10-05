/* Real browser + real saved server data. No mock routes or secret-bearing output. */
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const {enterValue} = require('./browser-input.cjs')

async function run({playwright, browserType, executablePath, env, outputDirectory, fixture}) {
  const browser = await playwright[browserType].launch({headless: true, executablePath, ...(process.env.QA_BROWSER_CHANNEL ? {channel: process.env.QA_BROWSER_CHANNEL} : {})})
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}, acceptDownloads: true})
  const errors = []
  page.on('pageerror', () => errors.push('JavaScript runtime error'))
  let stage = 'login'
  const prefix = 'qa-ui-' + browserType + '-' + Date.now()
  const timings = []
  const open = async (link, ready) => {
    const started = performance.now()
    await page.getByRole('link', {name: link, exact: true}).click()
    await ready()
    timings.push({screen: link, seconds: +( (performance.now() - started) / 1000).toFixed(4)})
  }
  const login = async role => {
    if (await page.getByRole('button', {name: 'Выйти', exact: true}).count()) {
      await page.getByRole('button', {name: 'Выйти', exact: true}).click()
    }
    await page.getByLabel('Аккаунт', {exact: true}).selectOption(role)
    await enterValue(page.getByLabel('Пароль', {exact: true}), env.DIPLOMA_SEED_PASSWORD)
    await page.getByRole('button', {name: 'Войти', exact: true}).click()
    await page.getByRole('button', {name: 'Выйти', exact: true}).waitFor()
  }
  let reviewId, confirmationId
  try {
    await page.goto('http://127.0.0.1:5173/login')
    await login('admin')
    await page.getByRole('heading', {name: 'Правила антифрода', exact: true}).waitFor()
    stage = 'rule builder and templates'
    await page.getByRole('button', {name: '+ Новое правило', exact: true}).click()
    await enterValue(page.getByLabel('Название', {exact: true}).first(), prefix + '-review')
    await page.getByLabel('Проверяемое действие', {exact: true}).selectOption('pay')
    await page.getByLabel('Механизм', {exact: true}).selectOption('all')
    await page.getByRole('button', {name: '+ Условие', exact: true}).click()
    const fields = page.getByLabel('Поле', {exact: true})
    await fields.nth(0).selectOption('amount'); await fields.nth(1).selectOption('receipt')
    await page.getByLabel('Сравнение', {exact: true}).nth(0).selectOption('gt')
    await page.getByLabel('Сравнение', {exact: true}).nth(1).selectOption('eq')
    await enterValue(page.getByLabel('Значение / порог', {exact: true}).nth(0), '400')
    await enterValue(page.getByLabel('Значение / порог', {exact: true}).nth(1), prefix)
    await page.getByRole('button', {name: 'Сохранить как новый шаблон', exact: true}).click()
    await page.getByText('Создан самостоятельный шаблон.', {exact: true}).waitFor()
    const saved = page.waitForResponse(r => r.url().endsWith('/api/admin/rules') && r.request().method() === 'POST')
    await page.getByRole('button', {name: 'Сохранить правило', exact: true}).click()
    reviewId = (await (await saved).json()).id
    await page.getByRole('heading', {name: 'Сохранённые шаблоны', exact: true}).waitFor()
    await page.locator('.list-row').filter({hasText: prefix + '-review'}).getByRole('button', {name: 'Создать правило', exact: true}).click()
    await enterValue(page.getByLabel('Название', {exact: true}).first(), prefix + '-confirm')
    await page.getByLabel('Реакция', {exact: true}).selectOption('CONFIRM')
    const second = page.waitForResponse(r => r.url().endsWith('/api/admin/rules') && r.request().method() === 'POST')
    await page.getByRole('button', {name: 'Сохранить правило', exact: true}).click()
    confirmationId = (await (await second).json()).id
    stage = 'watchlist'
    await page.getByRole('heading', {name: 'Активные настройки', exact: true}).waitFor()
    await enterValue(page.getByLabel('Название', {exact: true}), prefix + '-list')
    await enterValue(page.getByLabel('Значения через запятую', {exact: true}), 'Alice, Bob')
    await page.getByRole('button', {name: 'Добавить список', exact: true}).click()
    const watchRow = page.locator('.list-row').filter({hasText: prefix + '-list'})
    await watchRow.getByRole('button', {name: 'Изменить', exact: true}).click()
    await enterValue(page.getByLabel('Значения через запятую', {exact: true}), 'Alice, Carol')
    await page.getByRole('button', {name: 'Сохранить список', exact: true}).click()
    await watchRow.getByText('Alice, Carol', {exact: true}).waitFor()
    stage = 'catalog'
    await open('Приложения и источники', () => page.getByRole('button', {name: 'Настроить', exact: true}).first().waitFor())
    await page.getByRole('button', {name: '+ Приложение', exact: true}).click()
    await enterValue(page.getByLabel('Идентификатор', {exact: true}), prefix)
    await enterValue(page.getByLabel('Название', {exact: true}), 'Проверка интерфейса ' + browserType)
    await page.getByRole('button', {name: '+ Поле', exact: true}).click()
    await page.getByRole('row').filter({has: page.getByLabel('Имя поля amount', {exact: true})}).getByRole('button', {name: 'Убрать', exact: true}).click()
    await page.getByRole('button', {name: '+ Поле', exact: true}).click()
    assert.equal(await page.getByLabel('Имя поля field_2', {exact: true}).count(), 1)
    await page.getByRole('row').filter({has: page.getByLabel('Имя поля field_3', {exact: true})}).getByRole('button', {name: 'Убрать', exact: true}).click()
    await enterValue(page.getByLabel('Имя поля field_2', {exact: true}), 'amount', true)
    await page.getByLabel('Название', {exact: true}).click()
    await page.getByLabel('Тип amount', {exact: true}).selectOption('number')
    await page.getByRole('button', {name: '+ Поле', exact: true}).click()
    const duplicateName = page.getByLabel('Имя поля field_2', {exact: true})
    await enterValue(duplicateName, 'amount', true)
    await page.getByLabel('Название', {exact: true}).click()
    assert.equal(await duplicateName.evaluate(input => input.validationMessage), 'Поле с таким именем уже существует')
    await enterValue(duplicateName, 'extra', true)
    await page.getByLabel('Название', {exact: true}).click()
    await page.getByRole('row').filter({has: page.getByLabel('Имя поля extra', {exact: true})}).getByRole('button', {name: 'Убрать', exact: true}).click()
    await enterValue(page.getByLabel('Имя поля amount', {exact: true}), 'cost', true)
    await page.getByLabel('Название', {exact: true}).click()
    await page.getByLabel('Источник cost', {exact: true}).selectOption('DB')
    const appSaved = page.waitForResponse(r => r.url().endsWith('/api/admin/applications') && r.request().method() === 'POST')
    await page.getByRole('button', {name: 'Сохранить каталог', exact: true}).click()
    const createdApp = await (await appSaved).json()
    await page.getByRole('button', {name: 'Скрыть', exact: true}).click()
    const sourceForm = page.locator('form').filter({has: page.getByRole('heading', {name: 'Источник PostgreSQL · только чтение', exact: true})})
    await sourceForm.getByLabel('Приложение', {exact: true}).selectOption(prefix)
    await enterValue(page.getByLabel('URL подключения', {exact: true}), 'postgresql+asyncpg://diploma_reader:' + env.DIPLOMA_READER_PASSWORD + '@postgres:5432/' + (env.POSTGRES_DB || 'diploma'))
    await enterValue(page.getByLabel('Разрешённые столбцы через запятую', {exact: true}), 'amount')
    await enterValue(sourceForm.locator('textarea'), 'cost=amount')
    await page.getByRole('button', {name: 'Сохранить источник', exact: true}).click()
    await page.getByText('Источник сохранён. Пароль не отображается повторно.', {exact: true}).waitFor()
    assert.equal(await page.getByLabel('URL подключения', {exact: true}).inputValue(), '')
    stage = 'employee creates and submits'
    await login('employee')
    await page.getByRole('button', {name: '+ Новая заявка', exact: true}).click()
    for (const [name, value] of Object.entries({'Назначение': prefix, 'Получатель': 'Учебный получатель', 'Номер чека': prefix, 'Продавец': 'QA'})) {
      await enterValue(page.getByLabel(name, {exact: true}), value)
    }
    await page.getByRole('button', {name: 'Сохранить', exact: true}).click()
    const expenseRow = page.getByRole('row').filter({hasText: prefix})
    await expenseRow.getByRole('button', {name: 'Отправить', exact: true}).click()
    await page.getByRole('button', {name: 'Выполнить: Отправка на согласование', exact: true}).click()
    await expenseRow.getByText('На согласовании', {exact: true}).waitFor()
    stage = 'manager approval'
    await login('manager')
    await expenseRow.getByRole('button', {name: 'Согласовать', exact: true}).click()
    await page.getByRole('button', {name: 'Выполнить: Согласование', exact: true}).click()
    await expenseRow.getByText('Согласовано руководителем', {exact: true}).waitFor()
    stage = 'accountant requests review and confirmation'
    await login('accountant')
    await expenseRow.getByRole('button', {name: 'Проверить выплату', exact: true}).click()
    await page.locator('.decision').getByText('Ручная проверка', {exact: true}).first().waitFor()
    const recent = await page.request.get('http://127.0.0.1:5173/api/demo/decisions')
    const attempts = await recent.json()
    const pending = attempts.find(d => d.action === 'pay' && d.state === 'PENDING_REVIEW' && d.reasons.some(r => r.name === prefix + '-review'))
    assert(pending)
    stage = 'specialist review'
    await login('specialist')
    await enterValue(page.getByLabel('Идентификатор операции', {exact: true}), pending.operation_id)
    const filtered = page.waitForResponse(r => r.url().includes('/api/journal?') && r.url().includes(pending.operation_id))
    await page.getByRole('button', {name: 'Применить фильтры', exact: true}).click()
    await filtered
    await page.getByRole('row').filter({hasText: pending.operation_id}).getByRole('button', {name: 'Подробнее', exact: true}).click()
    await enterValue(page.getByLabel('Комментарий специалиста', {exact: true}), 'Проверено в браузере')
    await page.getByRole('button', {name: 'Одобрить', exact: true}).click()
    await page.locator('.decision').getByText('Ожидает подтверждения', {exact: true}).first().waitFor()
    await page.screenshot({path: path.join(outputDirectory, browserType + '-review.png'), fullPage: true})
    stage = 'initiator confirmation and safe execution'
    await login('accountant')
    await page.locator('.list-row').filter({hasText: pending.operation_id}).getByRole('button', {name: 'Открыть', exact: true}).click()
    await page.getByRole('button', {name: 'Подтверждаю эти значения', exact: true}).click()
    await page.getByRole('button', {name: 'Выполнить: Условная выплата', exact: true}).click()
    await expenseRow.getByText('Выплачено условно', {exact: true}).waitFor()
    await page.getByText('Действие сохранено; отдельное событие записано в историю.', {exact: true}).waitFor()
    // The GUI source maps a new domain name to the allowed DB column.
    const own = await (await page.request.get('http://127.0.0.1:5173/api/demo/requests')).json()
    assert.equal(own.find(r => r.title === prefix).recipient, 'Учебный получатель')
    const sourceCheck = await page.request.post('http://127.0.0.1:5173/api/checks', {headers: {'X-Application-Key': createdApp.api_key}, data: {application_id: prefix, operation_id: prefix, action: 'operation', initiator: 'browser', record_key: own.find(r => r.title === prefix).id, fields: {cost: 999}}})
    assert.equal(sourceCheck.status(), 200)
    assert.equal((await sourceCheck.json()).checked_values.cost, '500')
    stage = 'registry download and history'
    await expenseRow.getByRole('button', {name: 'История', exact: true}).click()
    await page.getByRole('heading', {name: 'История: ' + prefix, exact: true}).waitFor()
    await page.getByRole('button', {name: 'Выгрузить реестр', exact: true}).click()
    const download = page.waitForEvent('download')
    await page.getByRole('button', {name: 'Выполнить: Выгрузка реестра', exact: true}).click()
    assert.equal((await download).suggestedFilename(), 'реестр.csv')
    await page.screenshot({path: path.join(outputDirectory, browserType + '-expenses.png'), fullPage: true})
    stage = 'screen timings with 10000 events and 20 rules'
    await login('admin')
    const startedRules = performance.now()
    await page.getByLabel('Приложение', {exact: true}).selectOption(fixture.application_id)
    await page.getByText('20 включено', {exact: true}).waitFor()
    timings.push({screen: '20 правил', seconds: +((performance.now() - startedRules) / 1000).toFixed(4)})
    await open('Журнал решений', () => page.getByRole('button', {name: 'Подробнее', exact: true}).first().waitFor())
    await enterValue(page.getByLabel('Приложение', {exact: true}), fixture.application_id)
    const startedJournal = performance.now()
    const loadJournal = page.waitForResponse(r => r.url().includes('/api/journal?') && r.url().includes(fixture.application_id))
    await page.getByRole('button', {name: 'Применить фильтры', exact: true}).click()
    await loadJournal
    await page.getByText('Загружаем проверки…', {exact: true}).waitFor({state: 'hidden'})
    await page.getByRole('row').filter({hasText: fixture.application_id}).first().waitFor()
    timings.push({screen: 'Журнал с 10000 событий', seconds: +((performance.now() - startedJournal) / 1000).toFixed(4)})
    const startedCard = performance.now()
    await page.getByRole('button', {name: 'Подробнее', exact: true}).first().click()
    await page.getByRole('heading', {name: 'История решения', exact: true}).waitFor()
    timings.push({screen: 'Карточка проверки 20 правил', seconds: +((performance.now() - startedCard) / 1000).toFixed(4)})
    await page.getByRole('heading', {name: 'События, использованные правилами (429)', exact: true}).count() // Count is fixture-dependent; not an assertion.
    if (await page.getByRole('button', {name: 'Показать ещё события', exact: true}).count()) await page.getByRole('button', {name: 'Показать ещё события', exact: true}).click()
    await page.screenshot({path: path.join(outputDirectory, browserType + '-journal.png'), fullPage: true})
    assert.equal(errors.length, 0)
    return {browser: executablePath.includes('Edge') ? 'Microsoft Edge' : browserType === 'chromium' ? 'Chrome for Testing' : 'Firefox', engine: browserType, version: browser.version(), platform: process.platform, viewport: '1440x1000', production_build: true,
            flow: 'admin rules/template/list/catalog/DB source; employee submit; manager approve; accountant review+confirmation+pay+registry; saved journal',
            catalog_keyboard_rename: true, duplicate_field_name_rejected: true, adding_after_removal_preserves_fields: true,
            javascript_errors: errors.length, timings, all_screens_within_two_seconds: timings.every(t => t.seconds <= 2)}
  } catch (error) {
    await page.screenshot({path: path.join(outputDirectory, browserType + '-failure.png'), fullPage: true,
                           mask: [page.locator('input[type="password"]'), page.locator('.notice code')]}).catch(() => {})
    const headings = await page.locator('h1,h2').allTextContents().catch(() => [])
    console.log(JSON.stringify({failed_stage: stage, visible_headings: headings, error: error.message.split('\n')[0]}))
    throw new Error('Browser QA failed at ' + stage + ': ' + error.name)
  } finally {
    // Disable only this test's rules; preserve the saved records and explanations.
    if (reviewId || confirmationId) {
      const cleanup = await browser.newContext()
      await cleanup.request.post('http://127.0.0.1:5173/api/auth/login', {headers: {'X-Requested-With': 'antifraud-ui'}, data: {username: 'admin', password: env.DIPLOMA_SEED_PASSWORD}})
      const saved = await (await cleanup.request.get('http://127.0.0.1:5173/api/admin/rules?application_id=demo')).json()
      for (const rule of saved.filter(r => [reviewId, confirmationId].includes(r.id))) {
        const {id, version, ...body} = rule
        void version
        await cleanup.request.put('http://127.0.0.1:5173/api/admin/rules/' + id, {headers: {'X-Requested-With': 'antifraud-ui'}, data: {...body, enabled: false}})
      }
      await cleanup.close()
    }
    await browser.close()
  }
}
module.exports = {run}
