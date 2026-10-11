import {
  CheckCircle,
  Clock,
  MapPin,
  WarningCircle,
} from "@phosphor-icons/react";
import type { Dish, Recommendation, Review, Source, Status } from "../types";
import { Evidence, SourceLink } from "./Evidence";

const labels: Record<Status, string> = {
  supported: "Matches your request",
  confirmation: "Check details",
  excluded: "Does not fit",
};

function price(dish: Dish) {
  if (dish.price === null) return "Price unverified";
  let amount: string;
  try {
    amount = new Intl.NumberFormat("en", {
      style: "currency",
      currency: dish.currency ?? "EUR",
    }).format(dish.price);
  } catch {
    amount = `${dish.price.toFixed(2)} ${dish.currency ?? ""}`;
  }
  return dish.price_kind === "from" ? `From ${amount}` : amount;
}

function DishRow({
  dish,
  sources,
}: {
  dish: Dish;
  sources: Map<string, Source>;
}) {
  return (
    <div
      className={`dish-row ${dish.status === "excluded" ? "dish-excluded" : ""}`}
    >
      <div className="dish-heading">
        <h4>{dish.english_name}</h4>
        <span className="dish-price">{price(dish)}</span>
      </div>
      {dish.english_name !== dish.original_name && (
        <span className="original-name">{dish.original_name}</span>
      )}
      <p>{dish.description}</p>
      {(dish.ingredients?.length ?? 0) > 0 && (
        <p className="ingredients">
          <strong>Listed ingredients:</strong> {dish.ingredients!.join(", ")}
        </p>
      )}
      {(dish.exclusions?.length ?? 0) > 0 && (
        <p className="ingredient-checks">
          {dish
            .exclusions!.map(
              (fact) =>
                `${fact.ingredient}: ${fact.status === "absent" ? "absence supported" : fact.status === "present" ? "contains it" : "not confirmed"}`,
            )
            .join(" · ")}
        </p>
      )}
      <div className="dish-labels">
        <span>
          {dish.vegan === "yes"
            ? "Vegan"
            : dish.vegetarian === "yes"
              ? "Vegetarian"
              : ""}
        </span>
        {dish.menu_category !== "regular" && (
          <span>{dish.menu_category.replace("_", " ")}</span>
        )}
        <span className={`text-${dish.status}`}>{labels[dish.status]}</span>
      </div>
      {dish.reasons.length > 0 && (
        <p className="dish-reasons">{dish.reasons.join(" ")}</p>
      )}
      <Evidence
        refs={[
          ...dish.menu_refs,
          ...dish.price_refs,
          ...dish.dietary_refs,
          ...(dish.ingredient_refs ?? []),
          ...(dish.exclusions ?? []).flatMap((fact) => fact.refs),
        ].filter(
          (ref, index, all) =>
            all.findIndex(
              (item) =>
                item.source_id === ref.source_id && item.quote === ref.quote,
            ) === index,
        )}
        sources={sources}
      />
    </div>
  );
}

function ReviewColumn({
  title,
  reviews,
  sources,
}: {
  title: string;
  reviews: Review[];
  sources: Map<string, Source>;
}) {
  return (
    <div className="review-column">
      <h4>{title}</h4>
      {reviews.length === 0 ? (
        <p className="muted">No evidence retrieved for this side.</p>
      ) : (
        reviews.map((review, index) => (
          <div className="review-item" key={index}>
            <span className="review-aspect">
              {review.aspect} · {review.source_type.replace("_", " ")}
              {review.review_date ? ` · ${review.review_date}` : " · undated"}
            </span>
            <p>{review.summary}</p>
            <Evidence refs={review.refs} sources={sources} />
          </div>
        ))
      )}
    </div>
  );
}

export default function RecommendationCard({
  item,
  index,
  sources,
}: {
  item: Recommendation;
  index: number;
  sources: Map<string, Source>;
}) {
  const suitable = item.dishes.filter((dish) => dish.status !== "excluded");
  const other = item.dishes.filter((dish) => dish.status === "excluded");
  return (
    <article className="restaurant">
      <div className="restaurant-top">
        <span className="restaurant-number">
          {String(index + 1).padStart(2, "0")}
        </span>
        <div className="restaurant-title">
          <h3>{item.name}</h3>
          <div className="restaurant-links">
            <SourceLink url={item.website}>Website</SourceLink>
            {item.menu_url && <SourceLink url={item.menu_url}>Menu</SourceLink>}
          </div>
        </div>
        <span className={`status-badge ${item.status}`}>
          {item.status === "supported" ? (
            <CheckCircle size={15} />
          ) : (
            <WarningCircle size={15} />
          )}
          {labels[item.status]}
        </span>
      </div>
      <p className="restaurant-explanation">{item.explanation}</p>
      {(item.address || item.location_summary) && (
        <div className="location">
          <MapPin size={16} />
          <span>
            {item.address}
            {item.address && item.location_summary ? " · " : ""}
            {item.location_summary}
          </span>
        </div>
      )}
      <Evidence refs={item.location_refs} sources={sources} />
      <div className="menu-section">
        <h4 className="section-label">Menu options</h4>
        {suitable.length ? (
          suitable
            .slice(0, 3)
            .map((dish, index) => (
              <DishRow key={index} dish={dish} sources={sources} />
            ))
        ) : (
          <p className="muted">No suitable menu items could be verified.</p>
        )}
      </div>
      {other.length > 0 && (
        <details className="other-menu">
          <summary>
            Other menu items and why they do not fit ({other.length})
          </summary>
          {other.map((dish, index) => (
            <DishRow key={index} dish={dish} sources={sources} />
          ))}
        </details>
      )}
      {suitable.length > 3 && (
        <details className="other-menu">
          <summary>More menu items ({suitable.length - 3})</summary>
          {suitable.slice(3).map((dish, index) => (
            <DishRow key={index} dish={dish} sources={sources} />
          ))}
        </details>
      )}
      <div className="review-grid">
        <ReviewColumn
          title="What people liked"
          reviews={item.reviews.filter(
            (review) =>
              review.polarity === "positive" || review.polarity === "mixed",
          )}
          sources={sources}
        />
        <ReviewColumn
          title="What to watch for"
          reviews={item.reviews.filter(
            (review) =>
              review.polarity === "negative" || review.polarity === "mixed",
          )}
          sources={sources}
        />
      </div>
      {item.availability_summary && (
        <div className="availability">
          <Clock size={16} />
          <p>{item.availability_summary}</p>
        </div>
      )}
      <Evidence refs={item.availability_refs} sources={sources} />
      {item.gaps.length > 0 && (
        <details className="gaps">
          <summary>
            <WarningCircle size={16} /> Uncertainties and missing evidence (
            {item.gaps.length})
          </summary>
          <ul>
            {item.gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}
