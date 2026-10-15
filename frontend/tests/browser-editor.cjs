const assert = require('node:assert/strict')
const path = require('node:path')
const {enterValue} = require('./browser-input.cjs')

async function run({playwright, browserType, executablePath, env, outputDirectory}) {
  const browser = await playwright[browserType].launch({headless:true, executablePath, ...(process.env.QA_BROWSER_CHANNEL ? {channel: process.env.QA_BROWSER_CHANNEL} : {})})
  const page = await browser.newPage({viewport:{width:1440,height:1000}})
  let stage = 'login errors'
  const errors = []
  page.on('pageerror', () => errors.push('runtime error'))
  const prefix = 'qa-editor-' + Date.now()
  const call = async (route, data, method='POST', key) => {
    const response = await page.request.fetch('http://127.0.0.1:5173/api' + route, {method, data, headers:{'X-Requested-With':'antifraud-ui', ...(key ? {'X-Application-Key':key} : {})}})
    assert.equal(response.status(),200)
    return response.json()
  }
  const save = async () => {
    const response = page.waitForResponse(r => r.url().includes('/api/admin/rules') && ['POST','PUT'].includes(r.request().method()))
    await page.getByRole('button',{name:'Сохранить правило',exact:true}).click()
    const saved = await response
    assert.equal(saved.status(),200)
    return saved.json()
  }
  try {
    await page.goto('http://127.0.0.1:5173/login')
    await page.getByLabel('Аккаунт',{exact:true}).selectOption('admin')
    await enterValue(page.getByLabel('Пароль',{exact:true}), 'incorrect-test-password')
    await page.getByRole('button',{name:'Войти',exact:true}).click()
    await page.getByText('Неверный логин или пароль',{exact:true}).waitFor()
    assert.equal(await page.getByLabel('Пароль',{exact:true}).inputValue(),'incorrect-test-password')
    await enterValue(page.getByLabel('Пароль',{exact:true}), env.DIPLOMA_SEED_PASSWORD)
    await page.getByRole('button',{name:'Войти',exact:true}).click()
    await page.getByRole('heading',{name:'Правила антифрода',exact:true}).waitFor()
    const fields = {object:{type:'string',source:'API',required:true}, amount:{type:'number',source:'API',required:true}, flag:{type:'boolean',source:'API',required:true}}
    const app = await call('/admin/applications',{id:prefix,name:'QA все редакторы',ttl_seconds:600,catalog:Object.fromEntries(['move','stop','handover'].map(action => [action,{fields}]))})
    await page.reload()
    await page.getByLabel('Приложение',{exact:true}).selectOption(prefix)
    await page.getByText('0 включено',{exact:true}).waitFor()
    stage = 'all eight mechanism forms'
    const kinds = ['field','duplicate','count','aggregate','sequence','previous','related','novelty']
    for (const kind of kinds) {
      await page.getByRole('button',{name:'+ Новое правило',exact:true}).click()
      await page.getByLabel('Механизм',{exact:true}).selectOption(kind)
      await enterValue(page.getByLabel('Название',{exact:true}).first(), prefix + '-' + kind)
      await page.getByLabel('Правило включено',{exact:true}).uncheck()
      if (kind === 'field') {
        await page.getByRole('tab', {name: 'Шаблоны', exact: true}).click()
        await page.getByRole('tab', {name: 'Правила', exact: true}).click()
        assert.equal(await page.getByLabel('Название', {exact:true}).first().inputValue(), prefix + '-field')
      }
      if (kind === 'count') {
        await enterValue(page.getByLabel('Период, секунды',{exact:true}), '0')
        await page.getByRole('button',{name:'Сохранить правило',exact:true}).click()
        assert(await page.getByLabel('Период, секунды',{exact:true}).evaluate(input => input.validity.rangeUnderflow))
        assert.equal(await page.getByLabel('Название',{exact:true}).first().inputValue(),prefix + '-' + kind)
        await enterValue(page.getByLabel('Период, секунды',{exact:true}), '60')
      }
      await save()
      await page.getByRole('row').filter({hasText:prefix + '-' + kind}).waitFor()
    }
    stage = 'boolean value and retained server validation error'
    await page.getByRole('button',{name:'+ Новое правило',exact:true}).click()
    await enterValue(page.getByLabel('Название',{exact:true}).first(), prefix + '-boolean')
    await page.getByLabel('Поле',{exact:true}).selectOption('flag')
    const invalid = page.waitForResponse(r => r.url().endsWith('/api/admin/rules') && r.request().method() === 'POST')
    await page.getByRole('button',{name:'Сохранить правило',exact:true}).click()
    assert.equal((await invalid).status(),422)
    await page.getByText('Сравнение больше/меньше допускается только для числа',{exact:true}).waitFor()
    assert.equal(await page.getByLabel('Название',{exact:true}).first().inputValue(),prefix + '-boolean')
    await page.getByLabel('Сравнение',{exact:true}).selectOption('eq')
    await page.getByLabel('Значение / порог',{exact:true}).selectOption('true')
    await page.getByLabel('Реакция',{exact:true}).selectOption('BLOCK')
    const rule = await save()
    const payload = {application_id:prefix,operation_id:prefix,action:'move',initiator:'test',fields:{object:'one',amount:100,flag:true}}
    const blocked = await call('/checks',payload,'POST',app.api_key)
    assert.equal(blocked.state,'REJECTED')
    assert.equal((await call('/checks',{...payload,operation_id:prefix + '-false',fields:{...payload.fields,flag:false}},'POST',app.api_key)).state,'APPROVED')
    stage = 'template edit, independent clone and delete'
    await page.getByRole('row').filter({hasText:prefix + '-boolean'}).getByRole('button',{name:'Настроить',exact:true}).click()
    await page.getByRole('button',{name:'Сохранить как новый шаблон',exact:true}).click()
    await page.getByText('Создан самостоятельный шаблон.',{exact:true}).waitFor()
    await page.getByRole('button',{name:'Закрыть',exact:true}).click()
    await page.getByRole('tab', {name: 'Шаблоны', exact: true}).click()
    const templateRow = page.locator('.list-row').filter({hasText:prefix + '-boolean'})
    await templateRow.getByRole('button',{name:'Изменить шаблон',exact:true}).click()
    await enterValue(page.getByLabel('Название',{exact:true}).first(), prefix + '-template-v2')
    await page.getByLabel('Значение / порог',{exact:true}).selectOption('false')
    await page.getByRole('button',{name:'Сохранить шаблон',exact:true}).click()
    const edited = page.locator('.list-row').filter({hasText:prefix + '-template-v2'})
    await edited.getByText('Версия 2',{exact:true}).waitFor()
    await edited.getByRole('button',{name:'Создать правило',exact:true}).click()
    await enterValue(page.getByLabel('Название',{exact:true}).first(), prefix + '-copy')
    await page.getByLabel('Правило включено',{exact:true}).uncheck()
    await save()
    await page.getByRole('tab', {name: 'Шаблоны', exact: true}).click()
    await edited.getByRole('button',{name:'Удалить',exact:true}).click()
    await edited.waitFor({state:'hidden'})
    const rules = await call('/admin/rules?application_id=' + prefix,undefined,'GET')
    assert.equal(rules.find(r => r.id === rule.id).expression.value,true)
    assert.equal(rules.find(r => r.name === prefix + '-copy').expression.value,false)
    stage = 'boolean watchlist edit/delete'
    await page.getByRole('tab', {name: 'Списки наблюдения', exact: true}).click()
    await enterValue(page.getByLabel('Название',{exact:true}), prefix + '-list')
    await page.getByLabel('Тип значений',{exact:true}).selectOption('boolean')
    await enterValue(page.getByLabel('Значения через запятую',{exact:true}), 'true, false')
    await page.getByRole('button',{name:'Добавить список',exact:true}).click()
    const listRow = page.locator('.list-row').filter({hasText:prefix + '-list'})
    await listRow.getByRole('button',{name:'Изменить',exact:true}).click()
    await enterValue(page.getByLabel('Значения через запятую',{exact:true}), 'true')
    await page.getByRole('button',{name:'Сохранить список',exact:true}).click()
    await listRow.getByText('true',{exact:true}).waitFor()
    await listRow.getByRole('button',{name:'Удалить',exact:true}).click()
    await listRow.waitFor({state:'hidden'})
    stage = 'explicit demo reset button'
    await page.getByRole('link',{name:'Приложения и источники',exact:true}).click()
    await page.getByRole('tab', {name: 'Учебные данные', exact: true}).click()
    const reset = page.getByRole('button',{name:'Вернуть демо',exact:true})
    assert(await reset.isDisabled())
    await enterValue(page.getByLabel('Подтверждение возврата',{exact:true}), 'Вернуть учебное демо')
    if (process.env.QA_SKIP_DEMO_RESET !== '1') {
      await reset.click()
      await page.getByText('Учебные заявки восстановлены; прежние данные и журнал сохранены',{exact:true}).waitFor()
    } else {assert(await reset.isEnabled())}
    await page.screenshot({path:path.join(outputDirectory,'editor-reset.png'),fullPage:true})
    assert.equal(errors.length,0)
    return {browser:executablePath.includes('Edge') ? 'Microsoft Edge' : browserType === 'chromium' ? 'Chrome for Testing' : 'Firefox',version:browser.version(),platform:process.platform,mechanism_forms:kinds,invalid_period_retains_input:true,
            invalid_type_retains_input:true,tab_switch_retains_draft:true,boolean_rule_checks:true,template_edit_copy_delete:true,watchlist_edit_delete:true,
            explicit_reset:process.env.QA_SKIP_DEMO_RESET !== '1',javascript_errors:errors.length}
  } catch(error) {
    throw new Error('Browser QA failed at ' + stage + ': ' + error.message.split('\n')[0])
  } finally {await browser.close()}
}
module.exports = {run}
