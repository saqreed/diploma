db = db.getSiblingDB('lab');
db.operations.insertMany([
  {_id:ObjectId('000000000000000000000001'),id:1,batch:'duplicate',amount:Decimal128('11500.1250'),recipient:'Учебный получатель',active:true,unsupported:{nested:1}},
  {_id:ObjectId('000000000000000000000002'),id:2,batch:'duplicate',amount:Decimal128('4500.0000'),recipient:'Другой получатель',active:false},
  {_id:ObjectId('000000000000000000000003'),id:3,batch:'empty'},
  {_id:ObjectId('000000000000000000000004'),id:4,batch:'wrong',amount:'wrong',recipient:'Неверный тип',active:true}
]);
db.createUser({user:'lab_reader',pwd:process.env.SOURCE_LAB_READER_PASSWORD,roles:[{role:'read',db:'lab'}]});
db.createUser({user:'lab_denied',pwd:process.env.SOURCE_LAB_READER_PASSWORD,roles:[]});
db.createUser({user:'lab_writer',pwd:process.env.SOURCE_LAB_READER_PASSWORD,roles:[{role:'readWrite',db:'lab'}]});
