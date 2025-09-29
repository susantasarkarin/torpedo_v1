"use client"

import { useState } from "react"
import { useNavigate } from "react-router-dom"
import "./Templates.css"

function Templates() {
  const navigate = useNavigate()
  const [showPreviewModal, setShowPreviewModal] = useState(false)
  const [previewContent, setPreviewContent] = useState("")
  const [previewTitle, setPreviewTitle] = useState("")
    const [saving, setSaving] = useState(false) // added

  const sampleTemplates = [
    {
      id: 1,
      name: "Introductory Mail",
      category: "Outreach",
      usage: 45,
      lastUsed: "2024-01-15",
      subject: "Introductory mail in response to your LinkedIn request",
      htmlContent: `<!DOCTYPE html>
<html>
<head>
<style>
  body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
  .container { max-width: 600px; margin: 20px auto; padding: 20px; border: 1px solid #eee; border-radius: 8px; }
  .header { font-size: 20px; color: #0056b3; margin-bottom: 15px; }
  .footer { margin-top: 20px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px; }
  .signature { margin-top: 20px; padding-top: 10px; border-top: 1px solid #eee; }
  .signature-name { font-weight: bold; font-size: 16px; margin-bottom: 5px; }
  .signature-title { color: #0056b3; font-size: 14px; margin-bottom: 10px; }
  .social-icons img { width: 24px; height: 24px; margin-right: 5px; }
  .company-info { display: flex; align-items: center; margin-top: 15px; }
  .company-logo { height: 40px; margin-right: 15px; }
  .contact-details { font-size: 12px; }
  .contact-details div { display: flex; align-items: center; margin-bottom: 5px; }
  .contact-details img { width: 16px; height: 16px; margin-right: 5px; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">Introductory Mail</div>
    <p>Hi {{contact.name}},</p>
    <p>Greetings from {{sender.companyName}}.</p>
    <p>First, thanks for connecting on LinkedIn and giving us the opportunity to take this discussion forward.</p>
    <p>{{sender.companyName}} provides multi-country fieldwork services across a wide range of sectors. Headquartered in {{sender.headquarters}}, we manage, analyze, and consult with clients on custom-built qualitative and quantitative studies for various industries.</p>
    <p>We are experienced in conducting Public Opinion Poll, Mystery Shopping, Custom Research, Car Clinics, Dyad/Triad Interviews, Ethnographic research, Tracking Studies, Data Collection, Omnibus Solutions, Innovation & Product Development, Brand & Communication, Customer Strategies, Transcriptions, Translations, Online Market Research, Shopper, Desk Research etc.</p>
    <p>Do let us know your availability so that we can have a quick call within this week to understand your requirements.</p>
    <p>Best Regards,</p>
    <div class="signature">
      <p class="signature-name">{{sender.name}}</p>
      <p class="signature-title">{{sender.title}} - {{sender.companyName}}</p>
      <div class="social-icons">
        <a href="https://linkedin.com">
  <img src="https://img.icons8.com/fluency/48/linkedin.png" alt="LinkedIn">
</a>
       <a href="https://instagram.com">
  <img src="https://img.icons8.com/color/48/instagram-new.png" alt="Instagram">
</a>
       <a href="https://facebook.com">
  <img src="https://img.icons8.com/color/48/facebook.png" alt="Facebook">
</a>
      <div class="company-info">
        <img src="data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBwgIDwgIDRAQDQ0IEAoICAgPDRAICQgQFR0XGBURExMYKCkgJCYxHBMTIT0tJikrLi8vIx8zPzM4PzYtOisBCgoKDg0OGBAQGjcgIB0rLS0tLSs3LSstKystKy0tLTctLS0xLSs3Ky0tKys0Ky04LSsrNy0tNy0uNy0xNysuK//AABEIAMgAyAMBEQACEQEDEQH/xAAcAAEAAwADAQEAAAAAAAAAAAAAAQYHAgQFCAP/xABEEAABAwEBCgkKBgAHAQAAAAAAAQIDBAUGBxETFiFSU5OyMTRBVGF0kZLSEjM1cXJzgaKx0RUXIjJRoSNCQ2KCweEU/8QAGgEBAAMBAQEAAAAAAAAAAAAAAAEFBgQCA//EACkRAQABAQYHAQACAwAAAAAAAAABAgMEBRESURMVITEzQVIUMnEiI2H/2gAMAwEAAhEDEQA/ANxAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAOLnNbnVUT1rgQDjjo9JveQBjo9JveQBjo9JveQBjo9JveQBjo9JveQBjo9JveQBjo9JveQBjo9JveQBjo9JveQBjo9JveQBjo9JveQBjo9JveQBjo9JveQDk1zXZ0VF5My4UA5AAAAAAAAAAACh35PR9L1uHclAxoAAAAAAAAAAAAAADZLzXEKzrcu5EBfQAAAAAAAAAABQ78no+l63DuSgY0AAAAAAAAAAAAAABsl5riFZ1uXciAvoAAAAAAAAAAA6loWdR2gxIaiNkzGuSVsb2o9qOTCmHB6lUDz8kbnuZ0+yQBkjc9zOn2SAMkbnuZ0+yQBkjc9zOn2SAMkbnuZ0+yQBkjc9zOn2SAMkbnuZ0+yQBkjc9zOn2SAMkbneZ0+yQBkjc7zODZoBXrp729m1cb5aFqU1QxFcyNHKtNP/ALVReD1oBjksb4nPjcitdGrmPYuZzVThRU+CgcQNkvNcQrOty7kQF9AAAAAAAAAAAACAA7o6pCQAAAAAIAASB8/XfxsjtS12tTAiyNkVOlzWq5e1VAr4GyXmuIVnW5dyIC+gAAAAAAAAAAApEzkK1at0yRKsVOiPVuZ0y52fBOUpL3i3D6WfVaXfDqq+tfR5DrorTXPjEToRjM39FXOK3jvqd0YdYR6MobU1nyM+xHNLz9J5fYbGUNqaz5GfYc0vP0cusNjKG1NZ8jPsOaXn6OX2GxlDams+Rn2HNLz9HL7DYyhtTWfIz7Dml5+jl9hsZQ2prPkZ9hzS8/Ry+w2THdBaaq1MZwqiL+hn2PpZ4peZqiJl5rw+xiM4hekNXT1iJlnsknoYDfF9K2t7cW4wCuAbJea4hWdbl3IgL6AAAAAAAAAAQB5N01U6mp3+TmdMqQtdyphzr/SKV2JW2ixl2XKyiu2hRTHzObShADoZbg/szz7BIAAAHKL9zPW09Wf8oeK5jKWnIb2P4wyKT0MBvi+lbW9uLcYBXANkvNcQrOty7kQF9AAAAAAAAAAIAr92fmYPeJ9FKXGfFCxwzyqeZdoAke1ZVz09W1Jnri2OztzeU96FtdcJrtf86uitvGIU2c5U9Xp5Jwa1/Y0sJwWn6cnNK9jJKDWv7Gkclp+jmlexklBrX9jRyWn6OaV7GSUGtf2NHJafo5pXsZJQax/Y0clp+jmleyW3KQIqLjH/AKVReBD1Tg9nE55onE6pjLJYkzZi5iMoyViSRgN8X0ra3txbjAK4Bsl5riFZ1uXciAvoAAAAAAAAABAFfuz8zB7xPopS4z4oWOG+SVPMv3hoI7OxZ0TZpqeJeB72I5P5TDwHTdLOK7WmHwvFWmyqlpDURERP4+GA3FMZQy0pJQAAAAAAAAfPF2tZFW2jalRGuFjpVYx3Cj/JRG4cP/EDxQNkvNcQrOty7kQF9AAAAAAAAAAIAr92fmYPeJ9FKXGfFCxwzySp5l/+NA7tjcYpPeMOy4Rlb0uW+x/ploiG1hmAkUSrvoWRTST0zoalXQPkhc5GxK1VauBVTC7oA/P82LG1FV3YvEA/NixtRVd2LxAPzYsbUVXdi8QD82LG1FV3YvEA/NextRVd2LxAV66e+ZUV8clJRxup2SorJalzkdUKi8jUTMn9gZ8AA3O9dQupLNp3OTAtY+WswLw4FwI1exqL8QLcAAAAAAAAAAQBX7s/Mwe8T6KUuM+KFlhnklTzLr93bG4xR+8Ydlw89LlvnhqaIbWOzMBI+bLc43aXWKnecB0QAAAAAAAPSuboILSq6GimkSKOoe1kki5sKaKdK4MCesD6LhiZC2OFiI1kSNjjYmZrGpmRE/oD9AAAAAAAAAACAK/dn5mD3ifRSlxnxQssM8kqeZdfu7Y3GKP3jDsuHnpct88NTRDax2ZgJGG2tcRdJNUV0zKVzmSzTyRuxkKI5FcqouBV6UA6mQd0/NHbWHxAMg7p+aO2sPiAZB3T80dtYfEAyDun5o7aw+IBkHdPzR21h8QHk2pY9o2YqMqoZIVdh8lXtVGPwaLkzKB0QJRVRUVFwKmBUVMypg5UUD6EuMtZbWoaGscuGRWrDULyrIz9Kr8cGH4ge4AAAAAAAAAAQBX7s/Mwe8T6KUuM+KFlhnklTzL+l/7dyyHI2opFXWM+v/p2XLKLamXNe4zsamiIbWOzLhIAAAAABIHTtOzqW0opaOoYj45kVrmrwt/hzV5F6QPne2rOfZlTWUDlwrSyPiR3B5aJ+12DpRUA6QGy3nHq6z6lq/5KqVG9CKyNf+1AvgAAAAAAAAABAFfuz8zB7xPopS4z4oWOGeSVPMu0CUVUwKnCmBUXgVOkmmZpnOHmadUTC4WTdFBK1sc7vIkaiIr1TAyTpw8hqLnilFVOVpOUqG83Cuic6OsPT/FKDXR7RpYfrsZ9uPgWnyfilBroto0frsfo4Fpsn8UoNdFtGj9dj9HAtNj8UoNdFtGj9dj9HAtNkfilBroto0frsfo4FpsJadAubHRdH+I0RerKZ6VHBtI7w7iHRnnHR8UkpYDfF9K2t7cW4wCuAbJea4hWdbl3IgL6AAAAAAAAAACB4N10TpKdr0/0nse7oRcKfVUKrF6Jmxzj078Pqim1yn2phk+rRdwnsdAAM5RlAM5MoBnJlAM5MoBnJlDlF+5nrafSymeJDxaRGmWnJyG7p7QyU90noYDfF9K2t7cW4wCuAbJea4hWdbl3IgL6AAAAAAAAAAQB+c8TJmvicmFsiK1zf5Q+dpRFdE0T7TTVNM6o9KRatiVNG5ytRZI86tkRPKc3ochlb5h1pZdusNDdr9RaRlV3eUVuiY9O3VTPcGmrY1RuDTVsao3Bpq2NUbg01bGqNwaatjVG4NNWxqjdyi/cz1tPpZU1a46PNpVGmerTk5DdU9oZKe6T0MBvi+lbW9uLcYBXANkvNcQrOty7kQF9AAAAAAAAAAAAARMRI4LGxeROxFPHDp2etU7oxUei3sQcKjY11bmKj0W9iDhUbGurcxUei3sQcKjY11bmKj0W9iDhUbGurcxUei3sQcKjY11bmKj0W9iDhUbGurdOKj0U7EHDp2Nc7uZ9HkA/J0ELlVysaqrwqrUVVAf/ADU+gzuNA5MjYzM1EanDgREaigcwAAAAAAAAAAAAAAIIAAAAAAJJAgCQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD//Z" alt="Company Logo" class="company-logo">
        <div class="contact-details">
          <div><img src="https://img.icons8.com/ios-filled/50/new-post.png" alt="Email"> {{sender.email}}</div>
          <div><img src="https://img.icons8.com/ios-filled/50/domain.png" alt="Website"> {{sender.website}}</div>
          <div><img src="https://img.icons8.com/ios-filled/50/marker.png" alt="Location"> {{sender.address}}</div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>`,
    },
    {
      id: 2,
      name: "Follow-up Mail (1st)",
      category: "Follow-up",
      usage: 32,
      lastUsed: "2024-01-14",
      subject: "Following up on our previous discussion",
      htmlContent: `<!DOCTYPE html>
<html>
<head>
<style>
  body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
  .container { max-width: 600px; margin: 20px auto; padding: 20px; border: 1px solid #eee; border-radius: 8px; }
  .header { font-size: 20px; color: #0056b3; margin-bottom: 15px; }
  .footer { margin-top: 20px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px; }
  .signature { margin-top: 20px; padding-top: 10px; border-top: 1px solid #eee; }
  .signature-name { font-weight: bold; font-size: 16px; margin-bottom: 5px; }
  .signature-title { color: #0056b3; font-size: 14px; margin-bottom: 10px; }
  .social-icons img { width: 24px; height: 24px; margin-right: 5px; }
  .company-info { display: flex; align-items: center; margin-top: 15px; }
  .company-logo { height: 40px; margin-right: 15px; }
  .contact-details { font-size: 12px; }
  .contact-details div { display: flex; align-items: center; margin-bottom: 5px; }
  .contact-details img { width: 16px; height: 16px; margin-right: 5px; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">Follow-up Mail (1st)</div>
    <p>Hi {{contact.name}},</p>
    <p>Hope you are doing well.</p>
    <p>Just wanted to check if you had been able to go through my previous email. It would be great if we could connect sometime within this week or early next week for a quick chat.</p>
    <p>Best Regards,</p>
    <div class="signature">
      <p class="signature-name">{{sender.name}}</p>
      <p class="signature-title">{{sender.title}} - {{sender.companyName}}</p>
      <div class="social-icons">
        <a href="https://linkedin.com"><img src="/linkedin-icon.png" alt="LinkedIn"></a>
        <a href="https://instagram.com"><img src="/instagram-icon.png" alt="Instagram"></a>
        <a href="https://facebook.com"><img src="/facebook-icon.png" alt="Facebook"></a>
      </div>
      <div class="company-info">
        <img src="/generic-company-logo.png" alt="Company Logo" class="company-logo">
        <div class="contact-details">
          <div><img src="/email-icon.png" alt="Email"> {{sender.email}}</div>
          <div><img src="/generic-website-icon.png" alt="Website"> {{sender.website}}</div>
          <div><img src="/location-icon.png" alt="Location"> {{sender.address}}</div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>`,
    },
    {
      id: 3,
      name: "Follow-up Mail (2nd) - Case Study",
      category: "Follow-up",
      usage: 28,
      lastUsed: "2024-01-12",
      subject: "Following up: Case Studies in Healthcare",
      htmlContent: `<!DOCTYPE html>
<html>
<head>
<style>
  body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
  .container { max-width: 600px; margin: 20px auto; padding: 20px; border: 1px solid #eee; border-radius: 8px; }
  .header { font-size: 20px; color: #0056b3; margin-bottom: 15px; }
  .footer { margin-top: 20px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px; }
  .signature { margin-top: 20px; padding-top: 10px; border-top: 1px solid #eee; }
  .signature-name { font-weight: bold; font-size: 16px; margin-bottom: 5px; }
  .signature-title { color: #0056b3; font-size: 14px; margin-bottom: 10px; }
  .social-icons img { width: 24px; height: 24px; margin-right: 5px; }
  .company-info { display: flex; align-items: center; margin-top: 15px; }
  .company-logo { height: 40px; margin-right: 15px; }
  .contact-details { font-size: 12px; }
  .contact-details div { display: flex; align-items: center; margin-bottom: 5px; }
  .contact-details img { width: 16px; height: 16px; margin-right: 5px; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">Follow-up Mail (2nd) - Case Study</div>
    <p>Hi {{contact.name}},</p>
    <p>Hope you had been able to go through our previous mail.</p>
    <p>I would like to take this opportunity to highlight a couple of studies that we have done in the healthcare sector:</p>
    <p><strong>Project 1: Women's Health Product Potential</strong></p>
    <ul>
      <li>Objective: Understand the potential of a product related to Women's health (vitamins for improving fertility)</li>
      <li>Target: Gynaecologists and obstetricians aged &lt;65 and with at least 3 years of experience, who spend at least 50% of their time treating patients</li>
      <li>Methodology: IDI's</li>
      <li>Sample: 50 in each country</li>
      <li>Country: Italy, UK, France, Germany</li>
      <li>LOI: 15 minutes</li>
    </ul>
    <p><strong>Project 2: Fungal Nail Infection</strong></p>
    <ul>
      <li>Objective: Fungal Nail Infection</li>
      <li>Target: Consumers of the antifungal category (for fungal nail infection), All of them decision makers of the purchase, Pharmacy channel buyers, Representation of different brands of the market, 50% men and 50% women, Between 55 to 65 years of age</li>
      <li>Methodology: Focus Group</li>
      <li>Sample: 2 focus groups, 6-8 participants in each group</li>
      <li>Country: Germany</li>
      <li>LOI: 2 hours</li>
    </ul>
    <p>If you require support with your upcoming healthcare studies then do let us know. We would be happy to have a quick call within this week to understand your requirements.</p>
    <p>We look forward to hearing from you soon to initiate our business relationship!!</p>
    <p>Best Regards,</p>
    <div class="signature">
      <p class="signature-name">{{sender.name}}</p>
      <p class="signature-title">{{sender.title}} - {{sender.companyName}}</p>
      <div class="social-icons">
        <a href="https://linkedin.com"><img src="/linkedin-icon.png" alt="LinkedIn"></a>
        <a href="https://instagram.com"><img src="/instagram-icon.png" alt="Instagram"></a>
        <a href="https://facebook.com"><img src="/facebook-icon.png" alt="Facebook"></a>
      </div>
      <div class="company-info">
        <img src="/generic-company-logo.png" alt="Company Logo" class="company-logo">
        <div class="contact-details">
          <div><img src="/email-icon.png" alt="Email"> {{sender.email}}</div>
          <div><img src="/generic-website-icon.png" alt="Website"> {{sender.website}}</div>
          <div><img src="/location-icon.png" alt="Location"> {{sender.address}}</div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>`,
    },
    {
      id: 4,
      name: "Follow-up Mail (3rd) - Call Request",
      category: "Follow-up",
      usage: 67,
      lastUsed: "2024-01-16",
      subject: "Quick call this week?",
      htmlContent: `<!DOCTYPE html>
<html>
<head>
<style>
  body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
  .container { max-width: 600px; margin: 20px auto; padding: 20px; border: 1px solid #eee; border-radius: 8px; }
  .header { font-size: 20px; color: #0056b3; margin-bottom: 15px; }
  .footer { margin-top: 20px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px; }
  .signature { margin-top: 20px; padding-top: 10px; border-top: 1px solid #eee; }
  .signature-name { font-weight: bold; font-size: 16px; margin-bottom: 5px; }
  .signature-title { color: #0056b3; font-size: 14px; margin-bottom: 10px; }
  .social-icons img { width: 24px; height: 24px; margin-right: 5px; }
  .company-info { display: flex; align-items: center; margin-top: 15px; }
  .company-logo { height: 40px; margin-right: 15px; }
  .contact-details { font-size: 12px; }
  .contact-details div { display: flex; align-items: center; margin-bottom: 5px; }
  .contact-details img { width: 16px; height: 16px; margin-right: 5px; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">Follow-up Mail (3rd) - Call Request</div>
    <p>Hi {{contact.name}},</p>
    <p>Just wanted to check if you had been able to go through our previous mail.</p>
    <p>Also, can we schedule a call this week?</p>
    <p>Best Regards,</p>
    <div class="signature">
      <p class="signature-name">{{sender.name}}</p>
      <p class="signature-title">{{sender.title}} - {{sender.companyName}}</p>
      <div class="social-icons">
        <a href="https://linkedin.com"><img src="/linkedin-icon.png" alt="LinkedIn"></a>
        <a href="https://instagram.com"><img src="/instagram-icon.png" alt="Instagram"></a>
        <a href="https://facebook.com"><img src="/facebook-icon.png" alt="Facebook"></a>
      </div>
      <div class="company-info">
        <img src="/generic-company-logo.png" alt="Company Logo" class="company-logo">
        <div class="contact-details">
          <div><img src="/email-icon.png" alt="Email"> {{sender.email}}</div>
          <div><img src="/generic-website-icon.png" alt="Website"> {{sender.website}}</div>
          <div><img src="/location-icon.png" alt="Location"> {{sender.address}}</div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>`,
    },
    {
      id: 5,
      name: "Follow-up Mail (4th) - Discussion",
      category: "Follow-up",
      usage: 89,
      lastUsed: "2024-01-16",
      subject: "Continuing our discussion",
      htmlContent: `<!DOCTYPE html>
<html>
<head>
<style>
  body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
  .container { max-width: 600px; margin: 20px auto; padding: 20px; border: 1px solid #eee; border-radius: 8px; }
  .header { font-size: 20px; color: #0056b3; margin-bottom: 15px; }
  .footer { margin-top: 20px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px; }
  .signature { margin-top: 20px; padding-top: 10px; border-top: 1px solid #eee; }
  .signature-name { font-weight: bold; font-size: 16px; margin-bottom: 5px; }
  .signature-title { color: #0056b3; font-size: 14px; margin-bottom: 10px; }
  .social-icons img { width: 24px; height: 24px; margin-right: 5px; }
  .company-info { display: flex; align-items: center; margin-top: 15px; }
  .company-logo { height: 40px; margin-right: 15px; }
  .contact-details { font-size: 12px; }
  .contact-details div { display: flex; align-items: center; margin-bottom: 5px; }
  .contact-details img { width: 16px; height: 16px; margin-right: 5px; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">Follow-up Mail (4th) - Discussion</div>
    <p>Hi {{contact.name}},</p>
    <p>Just wanted to check if you had been able to go through our previous mail.</p>
    <p>We would be delighted to take the discussion forward.</p>
    <p>Best Regards,</p>
    <div class="signature">
      <p class="signature-name">{{sender.name}}</p>
      <p class="signature-title">{{sender.title}} - {{sender.companyName}}</p>
      <div class="social-icons">
        <a href="https://linkedin.com"><img src="/linkedin-icon.png" alt="LinkedIn"></a>
        <a href="https://instagram.com"><img src="/instagram-icon.png" alt="Instagram"></a>
        <a href="https://facebook.com"><img src="/facebook-icon.png" alt="Facebook"></a>
      </div>
      <div class="company-info">
        <img src="/generic-company-logo.png" alt="Company Logo" class="company-logo">
        <div class="contact-details">
          <div><img src="/email-icon.png" alt="Email"> {{sender.email}}</div>
          <div><img src="/generic-website-icon.png" alt="Website"> {{sender.website}}</div>
          <div><img src="/location-icon.png" alt="Location"> {{sender.address}}</div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>`,
    },
    {
      id: 6,
      name: "Follow-up Mail (5th) - New Projects",
      category: "Follow-up",
      usage: 12,
      lastUsed: "2024-01-10",
      subject: "Any new projects in your pipeline?",
      htmlContent: `<!DOCTYPE html>
<html>
<head>
<style>
  body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
  .container { max-width: 600px; margin: 20px auto; padding: 20px; border: 1px solid #eee; border-radius: 8px; }
  .header { font-size: 20px; color: #0056b3; margin-bottom: 15px; }
  .footer { margin-top: 20px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px; }
  .signature { margin-top: 20px; padding-top: 10px; border-top: 1px solid #eee; }
  .signature-name { font-weight: bold; font-size: 16px; margin-bottom: 5px; }
  .signature-title { color: #0056b3; font-size: 14px; margin-bottom: 10px; }
  .social-icons img { width: 24px; height: 24px; margin-right: 5px; }
  .company-info { display: flex; align-items: center; margin-top: 15px; }
  .company-logo { height: 40px; margin-right: 15px; }
  .contact-details { font-size: 12px; }
  .contact-details div { display: flex; align-items: center; margin-bottom: 5px; }
  .contact-details img { width: 16px; height: 16px; margin-right: 5px; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">Follow-up Mail (5th) - New Projects</div>
    <p>Hi {{contact.name}},</p>
    <p>Just wanted to check if you have any new projects in your pipeline where we can assist you?</p>
    <p>Best Regards,</p>
    <div class="signature">
      <p class="signature-name">{{sender.name}}</p>
      <p class="signature-title">{{sender.title}} - {{sender.companyName}}</p>
      <div class="social-icons">
        <a href="https://linkedin.com"><img src="/linkedin-icon.png" alt="LinkedIn"></a>
        <a href="https://instagram.com"><img src="/instagram-icon.png" alt="Instagram"></a>
        <a href="https://facebook.com"><img src="/facebook-icon.png" alt="Facebook"></a>
      </div>
      <div class="company-info">
        <img src="/generic-company-logo.png" alt="Company Logo" class="company-logo">
        <div class="contact-details">
          <div><img src="/email-icon.png" alt="Email"> {{sender.email}}</div>
          <div><img src="/generic-website-icon.png" alt="Website"> {{sender.website}}</div>
          <div><img src="/location-icon.png" alt="Location"> {{sender.address}}</div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>`,
    },
    {
      id: 7,
      name: "Follow-up Mail (6th) - Re-engagement",
      category: "Re-engagement",
      usage: 8,
      lastUsed: "2024-01-08",
      subject: "Re-engagement: How can we assist you?",
      htmlContent: `<!DOCTYPE html>
<html>
<head>
<style>
  body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
  .container { max-width: 600px; margin: 20px auto; padding: 20px; border: 1px solid #eee; border-radius: 8px; }
  .header { font-size: 20px; color: #0056b3; margin-bottom: 15px; }
  .footer { margin-top: 20px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px; }
  .signature { margin-top: 20px; padding-top: 10px; border-top: 1px solid #eee; }
  .signature-name { font-weight: bold; font-size: 16px; margin-bottom: 5px; }
  .signature-title { color: #0056b3; font-size: 14px; margin-bottom: 10px; }
  .social-icons img { width: 24px; height: 24px; margin-right: 5px; }
  .company-info { display: flex; align-items: center; margin-top: 15px; }
  .company-logo { height: 40px; margin-right: 15px; }
  .contact-details { font-size: 12px; }
  .contact-details div { display: flex; align-items: center; margin-bottom: 5px; }
  .contact-details img { width: 16px; height: 16px; margin-right: 5px; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">Follow-up Mail (6th) - Re-engagement</div>
    <p>Hi {{contact.name}},</p>
    <p>I hope you are well! I've tried getting in touch a few times and have not heard back. Just to refresh, our company {{sender.companyName}} handles multi-country fieldwork services and we would like to assist you in your upcoming studies.</p>
    <p>It would be really great if we could connect sometime during the week to tell you more about our services.</p>
    <p>Best Regards,</p>
    <div class="signature">
      <p class="signature-name">{{sender.name}}</p>
      <p class="signature-title">{{sender.title}} - {{sender.companyName}}</p>
      <div class="social-icons">
        <a href="https://linkedin.com"><img src="/linkedin-icon.png" alt="LinkedIn"></a>
        <a href="https://instagram.com"><img src="/instagram-icon.png" alt="Instagram"></a>
        <a href="https://facebook.com"><img src="/facebook-icon.png" alt="Facebook"></a>
      </div>
      <div class="company-info">
        <img src="/generic-company-logo.png" alt="Company Logo" class="company-logo">
        <div class="contact-details">
          <div><img src="/email-icon.png" alt="Email"> {{sender.email}}</div>
          <div><img src="/generic-website-icon.png" alt="Website"> {{sender.website}}</div>
          <div><img src="/location-icon.png" alt="Location"> {{sender.address}}</div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>`,
    },
    {
      id: 8,
      name: "Follow-up Mail (7th) - Final Attempt",
      category: "Follow-up",
      usage: 5,
      lastUsed: "2024-01-05",
      subject: "Final attempt to connect",
      htmlContent: `<!DOCTYPE html>
<html>
<head>
<style>
  body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
  .container { max-width: 600px; margin: 20px auto; padding: 20px; border: 1px solid #eee; border-radius: 8px; }
  .header { font-size: 20px; color: #0056b3; margin-bottom: 15px; }
  .footer { margin-top: 20px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px; }
  .signature { margin-top: 20px; padding-top: 10px; border-top: 1px solid #eee; }
  .signature-name { font-weight: bold; font-size: 16px; margin-bottom: 5px; }
  .signature-title { color: #0056b3; font-size: 14px; margin-bottom: 10px; }
  .social-icons img { width: 24px; height: 24px; margin-right: 5px; }
  .company-info { display: flex; align-items: center; margin-top: 15px; }
  .company-logo { height: 40px; margin-right: 15px; }
  .contact-details { font-size: 12px; }
  .contact-details div { display: flex; align-items: center; margin-bottom: 5px; }
  .contact-details img { width: 16px; height: 16px; margin-right: 5px; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">Follow-up Mail (7th) - Final Attempt</div>
    <p>Hi {{contact.name}},</p>
    <p>I didn’t hear back from you last week when I was looking for the appropriate person managing multi-country fieldwork services in your organization. If it makes sense to talk, let me know how your calendar looks. If not, who is the appropriate person?</p>
    <p>Best Regards,</p>
    <div class="signature">
      <p class="signature-name">{{sender.name}}</p>
      <p class="signature-title">{{sender.title}} - {{sender.companyName}}</p>
      <div class="social-icons">
        <a href="https://linkedin.com"><img src="/linkedin-icon.png" alt="LinkedIn"></a>
        <a href="https://instagram.com"><img src="/instagram-icon.png" alt="Instagram"></a>
        <a href="https://facebook.com"><img src="/facebook-icon.png" alt="Facebook"></a>
      </div>
      <div class="company-info">
        <img src="/generic-company-logo.png" alt="Company Logo" class="company-logo">
        <div class="contact-details">
          <div><img src="/email-icon.png" alt="Email"> {{sender.email}}</div>
          <div><img src="/generic-website-icon.png" alt="Website"> {{sender.website}}</div>
          <div><img src="/location-icon.png" alt="Location"> {{sender.address}}</div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>`,
    },
  ]

  const handlePreview = (htmlContent, title) => {
    setPreviewContent(htmlContent)
    setPreviewTitle(title)
    setShowPreviewModal(true)
  }

  const handleUseTemplate = async (template) => {
  try {
    setSaving(true)
    // save selected template to backend
    const res = await fetch("http://localhost:8000/templates/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(template),
    })
    const j = await res.json()
    if (!res.ok) throw new Error(j.detail || "Failed to save template")

    alert(`Template "${template.name}" saved to DB.`)

    // 🚀 go directly to Workflow page instead of CreateContacts
    navigate("/sales/campaign/list", { state: { selectedTemplate: template } })
  } catch (err) {
    console.error("Save template failed:", err)
    alert("Error saving template: " + (err.message || err))
  } finally {
    setSaving(false)
  }
}


  return (
    <div className="templates-container">
      {/* --- header, actions, stats remain unchanged --- */}

      <div className="templates-library">
        <div className="templates-library-header">
          <h3 className="card-title">Template Library</h3>
          <select className="form-input" style={{ width: "auto" }}>
            <option>All Categories</option>
            <option>Onboarding</option>
            <option>Sales</option>
            <option>Marketing</option>
            <option>Nurturing</option>
            <option>E-commerce</option>
            <option>Outreach</option>
            <option>Follow-up</option>
            <option>Re-engagement</option>
          </select>
        </div>

        <div className="templates-grid">
          {sampleTemplates.map((template) => (
            <div key={template.id} className="template-card">
              <div className="template-card-header">
                <div>
                  <h4 className="template-name">{template.name}</h4>
                  <span className="template-category">{template.category}</span>
                </div>
                <div style={{ textAlign: "right" }}>
                  <p className="template-meta">Used {template.usage} times</p>
                  <p className="template-meta">Last: {template.lastUsed}</p>
                </div>
              </div>
              <div className="template-actions">
                <button
                  className="btn btn-preview"
                  onClick={() => handlePreview(template.htmlContent, template.name)}
                >
                  Preview
                </button>
                <button
                  className="btn btn-use"
                  onClick={() => handleUseTemplate(template)}
                  disabled={saving}
                >
                  {saving ? "Saving..." : "Use Template"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {showPreviewModal && (
        <div className="modal-overlay" onClick={() => setShowPreviewModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close-btn" onClick={() => setShowPreviewModal(false)}>
              &times;
            </button>
            <h2 className="modal-title">Preview: {previewTitle}</h2>
            <iframe
              srcDoc={previewContent}
              title="Template Preview"
              className="template-preview-iframe"
              sandbox="allow-same-origin"
            ></iframe>
          </div>
        </div>
      )}
    </div>
  )
}

export default Templates