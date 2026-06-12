import { useSearchParams } from "react-router-dom";
import "./TrafficFlowParser.css";

const MESSAGES = {
  missing_id: {
    title: "Invalid Survey Link",
    text:
      "This survey link is incomplete — it is missing your respondent ID. " +
      "Please go back to your original survey invitation and click the link " +
      "again, or contact support if the problem continues.",
  },
  not_found: {
    title: "Survey Session Not Found",
    text:
      "We couldn't find your survey session. The link may have expired or " +
      "already been used — please start again from a fresh survey invitation.",
  },
  default: {
    title: "Thank You for Your Time",
    text:
      "Unfortunately, you haven't qualified for any surveys at this time. " +
      "We hope you'll try again later.",
  },
};

export default function SurveyError() {
  const [searchParams] = useSearchParams();
  const { title, text } = MESSAGES[searchParams.get("error")] || MESSAGES.default;

  return (
    <div className="survey-container">
      <div className="survey-card">
        <img
          src="/images/SF.png"
          alt="SurveyFieldwork Logo"
          className="survey-logo"
        />
        <h1 className="survey-title">{title}</h1>
        <hr className="survey-divider" />
        <p className="survey-text">{text}</p>
      </div>
    </div>
  );
}
