
the solution has

- a frontend app that gets audio and text from teh user
- a websocket server that connects the frontend with teh auzre api

Note: the websocket server will be replaced by a lambda aws

# for running the websocket server
cd app
cd backend
python app.py

# for testing websocket server
wscat -c ws://localhost:8765/realtime

{"type":"conversation.item.create","item":{"type":"function_call","name":"search","call_id":"call_12345","arguments":"{ \"query\": \"Tell me about AI\" }"}}


# running the fronted
---- then in other terminal
cd app
cd backend
chainlit run front_local.py
or 
chainlit run front_aws.py

run one or another depending with middletier you want to access



# running the original frontend, it is a totally different one
cd app/frontend
npm run dev
