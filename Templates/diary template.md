
--- 
创建日期: <% tp.file.creation_date() %>
心情指数: <% tp.system.prompt("今天心情如何？(1-5分)") %>

---
## 💼 学习
- [ ] <% tp.date.now("YYYY-MM-DD") %>
---
## 🏠 个人
- [ ]  <% tp.date.now("YYYY-MM-DD") %>

---
## 🔄 习惯追踪
- [ ] 雅思词汇 🔁 every day 📅 <% tp.date.now("YYYY-MM-DD") %>

<% tp.file.cursor() %>