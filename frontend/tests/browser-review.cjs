/* Negative user journeys against the isolated review API and persisted data. */
const assert = require('node:assert/strict')
const path = require('node:path')
const {enterValue} = require('./browser-input.cjs')

async function run({playwright, browserType, executablePath, env, outputDirectory}) {
  if (process.env.QA_ISOLATED_REVIEW !== '1') throw new Error('Review scenario requires isolated stand')
  const browser = await playwright[browserType].launch({headless: true, executablePath, ...(process.env.QA_BROWSER_CHANNEL ? {channel: process.env.QA_BROWSER_CHANNEL} : {})})
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}})
  const errors = []
  page.on('pageerror', () => errors.push('Runtime error'))
  const contexts = {}
  const prefix = 'qa-negative-' + browserType + '-' + Date.now()
  const rules = []
  let originalApp, originalSource, stage = 'setup'
  const call = async (role, url, body, method = body ? 'POST' : 'GET') => {
    const response = await contexts[role].fetch('/api' + url, {method, ...(body ? {data: body} : {})})
    assert.equal(response.status(), 200, url + ' status')
    return response.json()
  }
  const close = async () => {
    if (await page.getByRole('dialog').count()) await page.getByRole('button', {name: 'Закрыть панель', exact: true}).click()
  }
  const create = async suffix => call('employee', '/demo/requests', {amount: '500', recipient: 'Учебный получатель', title: prefix + suffix, receipt: prefix + suffix, vendor: 'QA', purchase_date: '2026-10-08'})
  const row = suffix => page.getByRole('row').filter({hasText: prefix + suffix})
  const search = async value => {
    const loaded = page.waitForResponse(r => r.url().includes('/api/demo/requests/page?') && new URL(r.url()).searchParams.get('search') === value)
    await enterValue(page.getByLabel('Поиск заявок', {exact: true}), value)
    const payload = await (await loaded).json()
    await page.getByText('Загружаем заявки…', {exact: true}).waitFor({state: 'hidden'})
    return payload
  }
  const sourcePayload = () => ({...Object.fromEntries(['table_name', 'key_field', 'allowed_fields', 'mapping'].map(k => [k, originalSource[k]])),
    url: 'postgresql+asyncpg://diploma_reader:' + env.DIPLOMA_READER_PASSWORD + '@postgres:5432/' + (env.POSTGRES_DB || 'diploma')})
  try {
    for (const role of ['admin', 'employee']) {
      contexts[role] = await playwright.request.newContext({baseURL: 'http://127.0.0.1:5173', extraHTTPHeaders: {'X-Requested-With': 'antifraud-ui'}})
      await call(role, '/auth/login', {username: role, password: env.DIPLOMA_SEED_PASSWORD})
    }
    originalApp = (await call('admin', '/admin/applications')).find(a => a.id === 'demo')
    originalSource = await call('admin', '/admin/sources/demo')
    for (const [suffix, reaction] of [['-block', 'BLOCK'], ['-cancel', 'CONFIRM'], ['-expire', 'CONFIRM'], ['-edit', 'CONFIRM']]) {
      rules.push(await call('admin', '/admin/rules', {application_id: 'demo', name: prefix + suffix, action: 'submit', reaction,
        expression: {kind: 'field', field: 'receipt', op: 'eq', value: prefix + suffix}}))
      await create(suffix)
    }
    await page.goto('http://127.0.0.1:5173/login')
    await page.getByLabel('Аккаунт', {exact: true}).selectOption('employee')
    await enterValue(page.getByLabel('Пароль', {exact: true}), env.DIPLOMA_SEED_PASSWORD)
    await page.getByRole('button', {name: 'Войти', exact: true}).click()
    await page.getByRole('heading', {name: 'Возмещение расходов', exact: true}).waitFor()
    assert.match(await page.title(), /Антифрод/i)
    assert.match(page.url(), /\/demo$/)
    assert.equal(await page.locator('vite-error-overlay').count(), 0)
    stage = '10000 requests, server search and pagination'
    const distant = await search('review-scale-00002')
    assert.equal(distant.total, 1)
    await page.getByRole('row').filter({hasText: distant.items[0].title}).waitFor()
    const first = await search('')
    assert(first.total >= 5000 && first.items.length === 50)
    assert(first.items.every(item => !('history' in item)))
    const paged = page.waitForResponse(r => r.url().includes('/api/demo/requests/page?') && new URL(r.url()).searchParams.get('offset') === '50')
    await page.getByRole('button', {name: 'Далее', exact: true}).click()
    const second = await (await paged).json()
    assert.equal(second.items.length, 50)
    assert(!second.items.some(item => first.items.some(old => old.id === item.id)))
    await page.getByText('Страница 2', {exact: true}).waitFor()
    stage = 'server validation preserves form'
    await page.getByRole('button', {name: '+ Новая заявка', exact: true}).click()
    for (const [name, value] of Object.entries({'Назначение': '   ', 'Получатель': 'Сохранённый ввод', 'Номер чека': prefix + '-invalid', 'Продавец': 'QA'})) await enterValue(page.getByLabel(name, {exact: true}), value)
    const invalid = page.waitForResponse(r => r.url().endsWith('/api/demo/requests') && r.request().method() === 'POST')
    await page.getByRole('button', {name: 'Сохранить черновик', exact: true}).click()
    assert.equal((await invalid).status(), 422)
    await page.getByRole('alert').waitFor()
    assert.equal(await page.getByLabel('Получатель', {exact: true}).inputValue(), 'Сохранённый ввод')
    await page.getByRole('button', {name: 'Закрыть', exact: true}).click()
    stage = 'BLOCK shows reason and next step'
    await search(prefix + '-block')
    await row('-block').getByRole('button', {name: 'Отправить на согласование', exact: true}).click()
    const decision = page.locator('.decision')
    await decision.getByText('Действие отклонено', {exact: true}).waitFor()
    await decision.getByText(prefix + '-block', {exact: true}).first().waitFor()
    assert.match(await decision.innerText(), /Действие не выполнено\. Разберите причину/)
    assert(!String(await decision.innerText()).includes('Действует до'))
    assert.equal(await decision.getByRole('button', {name: /Завершить/}).count(), 0)
    await page.screenshot({path: path.join(outputDirectory, browserType + '-block.png'), fullPage: false})
    await close()
    stage = 'cancel and refuse confirmation'
    await search(prefix + '-cancel')
    await row('-cancel').getByRole('button', {name: 'Отправить на согласование', exact: true}).click()
    await decision.getByText('Требуется подтверждение инициатора', {exact: true}).waitFor()
    await decision.getByRole('button', {name: 'Отменить попытку', exact: true}).click()
    await decision.getByText('Попытка отменена', {exact: true}).waitFor()
    await close()
    await row('-cancel').getByRole('button', {name: 'Отправить на согласование', exact: true}).click()
    await decision.getByRole('button', {name: 'Отказаться', exact: true}).click()
    await decision.getByText('Попытка отменена', {exact: true}).waitFor()
    await close()
    stage = 'expiry removes confirmation and gives next step'
    await call('admin', '/admin/applications/demo', {...originalApp, ttl_seconds: 2}, 'PUT')
    await search(prefix + '-expire')
    await row('-expire').getByRole('button', {name: 'Отправить на согласование', exact: true}).click()
    await decision.getByText('Срок решения истёк', {exact: true}).waitFor({timeout: 10000})
    assert.equal(await decision.getByRole('button', {name: 'Подтверждаю эти значения и действие', exact: true}).count(), 0)
    assert.match(await decision.innerText(), /Начните новую попытку/)
    await close()
    await call('admin', '/admin/applications/demo', originalApp, 'PUT')
    stage = 'editing cancels checked values'
    await search(prefix + '-edit')
    await row('-edit').getByRole('button', {name: 'Отправить на согласование', exact: true}).click()
    await decision.getByText('Требуется подтверждение инициатора', {exact: true}).waitFor()
    await close()
    await row('-edit').getByRole('button', {name: 'Изменить', exact: true}).click()
    await enterValue(page.getByLabel('Получатель', {exact: true}), 'Получатель после изменения')
    await page.getByRole('button', {name: 'Сохранить черновик', exact: true}).click()
    await row('-edit').getByRole('button', {name: 'Подробнее', exact: true}).click()
    await decision.getByText('Попытка отменена', {exact: true}).waitFor()
    assert.match(await page.getByRole('dialog').innerText(), /Получатель после изменения/)
    assert.equal(await decision.getByRole('button', {name: 'Подтверждаю эти значения и действие', exact: true}).count(), 0)
    await close()
    stage = 'unreachable source fails closed in UI'
    const dbApp = structuredClone(originalApp)
    dbApp.catalog.submit.fields.amount.source = 'DB'
    await call('admin', '/admin/sources/demo', {...sourcePayload(), url: sourcePayload().url.replace(':5432/', ':5433/')}, 'PUT')
    await call('admin', '/admin/applications/demo', dbApp, 'PUT')
    await create('-source')
    await search(prefix + '-source')
    await row('-source').getByRole('button', {name: 'Отправить на согласование', exact: true}).click()
    await decision.getByText('Не удалось прочитать настроенный источник данных', {exact: true}).waitFor()
    await decision.getByText('Действие отклонено', {exact: true}).waitFor()
    assert.equal(await decision.getByRole('button', {name: /Завершить/}).count(), 0)
    await page.screenshot({path: path.join(outputDirectory, browserType + '-source-error.png'), fullPage: false})
    await close()
    stage = 'mobile layout'
    await page.setViewportSize({width: 390, height: 844})
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    await page.screenshot({path: path.join(outputDirectory, browserType + '-mobile.png'), fullPage: false})
    assert.equal(errors.length, 0)
    return {browser: browserType, version: browser.version(), platform: process.platform, viewports: ['1440x1000', '390x844'],
      page_identity: true, meaningful_content: true, no_framework_overlay: true, javascript_errors: 0, real_api: true,
      server_pagination_10000: true, search_distant_record: true, invalid_form_keeps_input: true,
      block_reason_next_step: true, cancellation_and_refusal: true, expiry_next_step: true, edit_cancels_permission: true,
      source_error_denies: true, mobile_no_document_overflow: true}
  } catch (error) {
    await page.screenshot({path: path.join(outputDirectory, browserType + '-failure.png'), fullPage: false}).catch(() => {})
    const safe = String(error.message).split('\n')[0].slice(0, 200)
    throw new Error('Browser QA failed at ' + stage + ': ' + safe)
  } finally {
    if (originalApp) await call('admin', '/admin/applications/demo', originalApp, 'PUT')
    if (originalSource) await call('admin', '/admin/sources/demo', sourcePayload(), 'PUT')
    for (const rule of rules) await call('admin', '/admin/rules/' + rule.id, {...Object.fromEntries(Object.entries(rule).filter(([k]) => !['id', 'version'].includes(k))), enabled: false}, 'PUT')
    for (const context of Object.values(contexts)) await context.dispose()
    await browser.close()
  }
}
module.exports = {run}
