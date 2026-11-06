"""Demo data seeding (`flask seed`).

Populates shelters, a few demo users, and a catalogue of adoptable pets that
mirror the mock designs (Bruno, Daisy, Mochi, etc.). Idempotent: running it
again clears and rebuilds the demo rows.
"""
from __future__ import annotations

import click
from flask import Flask
from flask.cli import with_appcontext

from .extensions import db
from .models.content import FAQ, BlogPost, SuccessStory
from .models.pet import AgeGroup, Pet, PetStatus, Sex, Size, Species
from .models.shelter import Shelter
from .models.user import User, UserRole
from .models.health import MedicalRecord, OwnedPet, RecordType, Vaccination
from .models.community import Comment, Post, PostLike
from .models.learning import LearningPath, Lesson
from .learning_content import lesson_body
from .models.reminder import Notification
from .models.lifestyle import ExpenseFrequency, ExpenseItem, Place, PlaceCategory
from .models.vet import VetProfile


# Pet photos are served from local static files (downloaded into
# static/img/pets) so they always work, including offline, with no external
# dependency. The _u() helper builds the static path.
def _u(name: str) -> str:
    return f"/static/img/pets/{name}.jpg"


_PET_PHOTOS = {
    "Bruno": [_u("bruno")],
    "Daisy": [_u("daisy")],
    "Coco": [_u("coco")],
    "Milo": [_u("milo")],
    "Max": [_u("max")],
    "Mochi": [_u("mochi")],
    "Pixie": [_u("pixie")],
    "Ginger": [_u("ginger")],
    "Rocky": [_u("rocky")],
    "Snow": [_u("snow")],
    "Luna": [_u("luna")],
    "_default_dog": [_u("milo")],
    "_default_cat": [_u("mochi")],
    "_default_rabbit": [_u("snow")],
    "_default_bird": [_u("bird")],
    "_default_other": [_u("pixie")],
}


def _shelter(owner, name, slug, city, about, since, response, verified=True):
    # Use owner_id (not the relationship) to avoid a premature autoflush of the
    # backref before the Shelter is added to the session.
    return Shelter(
        owner_id=owner.id if owner else None,
        name=name,
        slug=slug,
        city=city,
        about=about,
        operating_since=since,
        avg_response_hours=response,
        is_verified=verified,
        contact_name=owner.full_name if owner else None,
    )


def _pet(shelter, **kw):
    kw.setdefault("status", PetStatus.AVAILABLE)
    return Pet(shelter=shelter, **kw)


def seed_data() -> dict:
    """Create demo data and return a summary of counts."""
    # ---- Clear existing demo rows (pets, shelters, demo users) ----
    Pet.query.delete()
    Shelter.query.delete()
    db.session.query(User).filter(User.email.like("%@demo.petship")).delete(
        synchronize_session=False
    )
    db.session.commit()

    # ---- Demo users ----
    def mkuser(email, first, last, role, verified=True):
        u = User(
            email=email,
            first_name=first,
            last_name=last,
            role=role,
            is_verified=verified,
        )
        u.set_password("password123")
        u.is_active = True
        db.session.add(u)
        return u

    kavya = mkuser("kavya@demo.petship", "Kavya", "S", UserRole.SHELTER)
    ravi = mkuser("ravi@demo.petship", "Ravi", "Kumar", UserRole.SHELTER)
    agalya = mkuser("agalya@demo.petship", "Agalya", "R", UserRole.ADOPTER)
    ananya = mkuser("ananya@demo.petship", "Ananya", "Rao", UserRole.VET)
    vikram = mkuser("vikram@demo.petship", "Vikram", "Iyer", UserRole.VET)
    sneha = mkuser("sneha@demo.petship", "Sneha", "Menon", UserRole.VET)
    second_chance_owner = mkuser(
        "secondchance@demo.petship", "Second Chance", "Applicant",
        UserRole.SHELTER, verified=False,
    )
    second_chance_owner.registration_status = "pending"
    second_chance_owner.is_active = False
    mkuser("admin@demo.petship", "Platform", "Admin", UserRole.ADMIN)
    db.session.commit()

    _seed_vets(ananya, vikram, sneha)
    _seed_health(agalya)
    _seed_lifestyle(agalya)
    _seed_learning()
    _seed_community(agalya, ananya)
    _seed_notifications(agalya)

    # ---- Shelters ----
    happy_paws = _shelter(
        kavya,
        "Happy Paws Shelter",
        "happy-paws",
        "Adyar, Chennai",
        "We rescue, rehabilitate, and rehome street animals across Chennai. "
        "Every pet is vaccinated, neutered, and microchipped before adoption.",
        2014,
        2.0,
    )
    purr_house = _shelter(
        ravi,
        "Purr House Shelter",
        "purr-house",
        "Velachery, Chennai",
        "A cat-focused rescue dedicated to finding calm homes for felines.",
        2018,
        3.0,
    )
    second_chance = _shelter(
        second_chance_owner,
        "Second Chance Home",
        "second-chance",
        "Trichy",
        "Giving senior and special-needs pets a loving second chance.",
        2019,
        4.0,
        verified=False,
    )
    db.session.add_all([happy_paws, purr_house, second_chance])
    db.session.flush()

    # ---- Pets (mirroring the mock catalogue) ----
    pets = [
        _pet(
            happy_paws, name="Bruno", species=Species.DOG, breed="Beagle mix",
            age_group=AgeGroup.YOUNG, age_text="2 yrs", size=Size.MEDIUM,
            sex=Sex.MALE, weight_kg=12, energy="high", distance_km=3,
            adoption_fee=2500,
            description="Bruno is a cheerful, curious pup who loves long walks and "
            "belly rubs. He's great with children, house trained, and ready to be "
            "someone's best friend.",
            health_tags=["Vaccinated", "Neutered", "Microchipped"],
            personality_tags=["Friendly", "Playful"],
            good_with=["kids"],
            views=1240,
        ),
        _pet(
            happy_paws, name="Daisy", species=Species.DOG, breed="Indie",
            age_group=AgeGroup.YOUNG, age_text="2 yrs", size=Size.MEDIUM,
            sex=Sex.FEMALE, weight_kg=10, energy="medium", distance_km=4,
            adoption_fee=2000,
            description="Gentle, quiet, loves cuddles with kids.",
            health_tags=["Vaccinated"], personality_tags=["Gentle", "Calm"],
            good_with=["kids"], views=860,
        ),
        _pet(
            happy_paws, name="Coco", species=Species.DOG, breed="Shih Tzu",
            age_group=AgeGroup.ADULT, age_text="4 yrs", size=Size.SMALL,
            sex=Sex.FEMALE, weight_kg=6, energy="low", distance_km=6,
            adoption_fee=3000,
            description="Lap dog, relaxed, apartment friendly.",
            health_tags=["Vaccinated", "Trained"], personality_tags=["Calm", "Lap dog"],
            good_with=["kids", "cats"], views=540,
        ),
        _pet(
            happy_paws, name="Milo", species=Species.DOG, breed="Indie",
            age_group=AgeGroup.BABY, age_text="6 mo", size=Size.MEDIUM,
            sex=Sex.MALE, weight_kg=5, energy="high", distance_km=2,
            adoption_fee=1500,
            description="A playful puppy looking for an active family.",
            health_tags=["Puppy"], personality_tags=["Energetic"], good_with=["dogs"],
            views=410,
        ),
        _pet(
            happy_paws, name="Max", species=Species.DOG, breed="Labrador",
            age_group=AgeGroup.ADULT, age_text="3 yrs", size=Size.LARGE,
            sex=Sex.MALE, weight_kg=28, energy="medium", distance_km=8,
            adoption_fee=2500,
            description="Patient family dog, great with toddlers.",
            health_tags=["Vaccinated", "Trained"], personality_tags=["Active", "Trained"],
            good_with=["kids"], views=980,
        ),
        _pet(
            purr_house, name="Mochi", species=Species.CAT, breed="Domestic tabby",
            age_group=AgeGroup.ADULT, age_text="3 yrs", size=Size.SMALL,
            sex=Sex.FEMALE, weight_kg=4.2, energy="low", distance_km=5,
            adoption_fee=1200,
            description="Calm, low-maintenance, great for beginners.",
            health_tags=["Vaccinated", "Spayed", "Microchipped"],
            personality_tags=["Calm", "Affectionate", "Indoor"],
            good_with=["kids"], views=720,
        ),
        _pet(
            purr_house, name="Pixie", species=Species.DOG, breed="Pug",
            age_group=AgeGroup.YOUNG, age_text="1 yr", size=Size.SMALL,
            sex=Sex.FEMALE, weight_kg=7, energy="low", distance_km=5,
            adoption_fee=1800,
            description="Small, gentle, enjoys short walks.",
            health_tags=["Neutered"], personality_tags=["Calm"], good_with=["kids"],
            views=610,
        ),
        _pet(
            purr_house, name="Ginger", species=Species.CAT, breed="Domestic shorthair",
            age_group=AgeGroup.YOUNG, age_text="1 yr", size=Size.SMALL,
            sex=Sex.MALE, weight_kg=3.8, energy="medium", distance_km=2,
            adoption_fee=1000,
            description="Curious and affectionate young cat.",
            health_tags=["Vaccinated"], personality_tags=["Curious"], good_with=["cats"],
            views=300,
        ),
        _pet(
            second_chance, name="Rocky", species=Species.DOG, breed="Retriever",
            age_group=AgeGroup.YOUNG, age_text="1 yr", size=Size.LARGE,
            sex=Sex.MALE, weight_kg=25, energy="high", distance_km=9,
            adoption_fee=2500,
            description="Sweet natured, still learning manners.",
            health_tags=["Vaccinated"], personality_tags=["Young", "Playful"],
            good_with=["dogs"], status=PetStatus.DRAFT, views=0,
        ),
        _pet(
            second_chance, name="Snow", species=Species.RABBIT, breed="Mini lop",
            age_group=AgeGroup.YOUNG, age_text="1 yr", size=Size.SMALL,
            sex=Sex.FEMALE, weight_kg=1.8, energy="low", distance_km=7,
            adoption_fee=800,
            description="A tiny rabbit with a huge personality.",
            health_tags=["Vaccinated"], personality_tags=["Quiet"], good_with=[],
            views=220,
        ),
        _pet(
            happy_paws, name="Luna", species=Species.DOG, breed="Husky mix",
            age_group=AgeGroup.YOUNG, age_text="2 yrs", size=Size.LARGE,
            sex=Sex.FEMALE, weight_kg=22, energy="high", distance_km=12,
            adoption_fee=3000,
            description="Energetic and smart, needs an active home.",
            health_tags=["Vaccinated"], personality_tags=["Energetic"], good_with=["dogs"],
            status=PetStatus.ADOPTED, views=1820,
        ),
    ]

    # Assign real, free pet photos (stable Unsplash image URLs — no account or
    # API key needed) so cards and detail pages show actual images.
    for pet in pets:
        pet.photos = _PET_PHOTOS.get(pet.name, _PET_PHOTOS["_default_" + pet.species.value])

    db.session.add_all(pets)
    db.session.commit()

    _seed_content()

    return {
        "users": db.session.query(User).count(),
        "shelters": db.session.query(Shelter).count(),
        "pets": db.session.query(Pet).count(),
        "available": db.session.query(Pet)
        .filter_by(status=PetStatus.AVAILABLE)
        .count(),
        "blog": db.session.query(BlogPost).count(),
        "stories": db.session.query(SuccessStory).count(),
        "faqs": db.session.query(FAQ).count(),
        "vets": db.session.query(VetProfile).count(),
    }


def _seed_notifications(user):
    """Seed a few starter notifications so the centre and bell aren't empty."""
    Notification.query.filter_by(user_id=user.id).delete()
    db.session.commit()
    db.session.add_all([
        Notification(user_id=user.id, category="health",
                     title="Vaccine due soon",
                     body="Mochi's rabies booster is due in 16 days. Book a vet now.",
                     link="/health/"),
        Notification(user_id=user.id, category="health",
                     title="Reminder: deworming tablet",
                     body="Give Mochi 1 tablet with her morning food.",
                     link="/lifestyle/reminders"),
        Notification(user_id=user.id, category="adoption",
                     title="Welcome to PetShip!",
                     body="Complete your profile to get better AI matches.",
                     link="/profile/", read=True),
    ])
    db.session.commit()


def _seed_community(agalya, vet):
    """Seed a couple of community posts with a comment."""
    Post.query.delete()
    db.session.commit()
    p1 = Post(author_id=agalya.id, title="Max's first beach day!",
              topic="Show & tell",
              body="Six months since adoption and he's a completely different dog. "
                   "Thank you PetShip family!")
    p2 = Post(author_id=agalya.id, title="Tips for a cat who won't stop hiding?",
              topic="New adopters",
              body="Adopted Luna three days ago and she's under the bed all day. "
                   "Is this normal?")
    db.session.add_all([p1, p2])
    db.session.flush()
    db.session.add(Comment(
        post_id=p2.id, author_id=vet.id,
        body="Totally normal! Give her a quiet safe room, keep routines "
             "predictable, and let her come to you. Most cats settle within two weeks."))
    db.session.commit()


def _seed_learning():
    """Seed the fixed set of built-in learning paths available to all users."""
    LearningPath.query.delete()
    db.session.commit()

    def path(slug, title, level, summary, duration, quizzes, lessons):
        p = LearningPath(slug=slug, title=title, level=level, summary=summary,
                         duration_min=duration, quiz_count=quizzes)
        db.session.add(p)
        db.session.flush()
        seen = set()
        position = 0
        for lesson_title, summary in lessons:
            title_key = lesson_title.strip().casefold()
            if title_key in seen:
                continue
            seen.add(title_key)
            position += 1
            db.session.add(Lesson(
                path_id=p.id,
                position=position,
                title=lesson_title,
                body=lesson_body(slug, lesson_title, summary),
            ))
        return p

    path("dog-parent", "Dog Parent", "Beginner",
         "Everything a dog owner needs, from day one onward.", 60, 1, [
             ("Bringing Your Dog Home", "Prepare a safe, comfortable space and help your dog settle gradually."),
             ("House Training Basics", "Use a consistent toilet area, routine, and positive reinforcement."),
             ("Feeding & Nutrition", "Provide balanced, life-stage-appropriate nutrition and fresh water."),
             ("Vet Care & Vaccinations", "Schedule regular examinations, vaccinations, and parasite prevention."),
             ("Leash Training", "Build comfortable, safe walking habits with positive practice."),
             ("Socialisation", "Introduce people, animals, sounds, and environments gradually."),
             ("Grooming & Building Trust", "Maintain hygiene while using patience and positive interactions."),
         ])
    path("cat-parent", "Cat Parent", "Beginner",
         "Core skills for a happy, healthy cat.", 45, 1, [
             ("Preparing Your Home for a Cat", "Create a quiet, secure home with litter, food, and hiding places."),
             ("Understanding Cat Behaviour", "Learn to recognise cat communication and body language."),
             ("Litter Training", "Provide and maintain a suitable litter area."),
             ("Feeding & Nutrition", "Choose complete cat food and support healthy hydration."),
             ("Vet Care & Vaccinations", "Maintain regular examinations and vaccination records."),
             ("Grooming & Hygiene", "Care for the coat, teeth, nails, and skin."),
             ("Bonding & Playtime", "Build trust through gentle interaction and enrichment."),
         ])
    path("rabbit-bonding", "Rabbit Bonding", "Beginner",
         "Build trust and bond with your rabbit.", 40, 1, [
             ("Understanding Rabbit Behaviour", "Recognise natural communication and prey-animal needs."),
             ("Preparing a Safe Living Space", "Provide a spacious, protected, rabbit-proofed environment."),
             ("Building Trust with Your Rabbit", "Use calm, ground-level interactions without chasing."),
             ("Rabbit Body Language", "Recognise comfort, fear, stress, and territorial behaviour."),
             ("Handling & Interaction", "Support rabbits safely while respecting their preferences."),
             ("Bonding with Multiple Rabbits", "Introduce compatible rabbits slowly and safely."),
             ("Rabbit Health & Hygiene", "Monitor eating, droppings, dental health, and hygiene."),
         ])
    path("swim-with-fish", "Swim with Fish", "Beginner",
         "Learn the essentials of setting up and caring for healthy aquarium fish.",
         40, 1, [
             ("Understanding Aquarium Fish", "Research species requirements, adult size, temperament, and compatibility."),
             ("Setting Up an Aquarium", "Choose a suitable tank, filtration, substrate, plants, and decorations."),
             ("Water Quality & Maintenance", "Cycle the aquarium and control ammonia, nitrite, nitrate, and pH."),
             ("Fish Feeding & Nutrition", "Provide a varied, species-appropriate diet without overfeeding."),
             ("Fish Compatibility", "Introduce compatible fish safely and avoid overcrowding."),
             ("Common Fish Diseases", "Recognise warning signs and seek aquatic veterinary advice."),
             ("Aquarium Cleaning & Care", "Maintain stable conditions through careful, routine care."),
         ])
    path("hamster-care", "Connecting with Hamsters", "Beginner",
         "Gentle handling and a happy habitat.", 30, 1, [
             ("Preparing a Hamster Home", "Provide deep bedding, hides, ventilation, and safe enrichment."),
             ("Understanding Hamster Behaviour", "Recognise natural activity patterns and signs of stress."),
             ("Building Trust with Your Hamster", "Allow gradual, voluntary interaction without sudden handling."),
             ("Handling & Interaction", "Scoop gently with both hands and keep the hamster low to the ground."),
             ("Feeding & Nutrition", "Use complete hamster food with measured, safe additions."),
             ("Exercise & Enrichment", "Provide daily running, digging, tunnels, and supervised exploration."),
             ("Health & Hygiene", "Spot-clean carefully and monitor for urgent health changes."),
         ])
    path("parrot-care", "Parrot Care", "Intermediate",
         "Enrichment and trust for a clever companion.", 50, 1, [
             ("Preparing a Home for Your Parrot", "Create a secure, spacious cage and bird-safe room."),
             ("Understanding Parrot Behaviour", "Recognise vocal, feather, and posture communication."),
             ("Building Trust & Communication", "Use gentle, predictable interaction and positive reinforcement."),
             ("Feeding & Nutrition", "Use formulated food with suitable vegetables and limited fruit."),
             ("Cage Setup & Enrichment", "Provide varied perches, toys, climbing, and supervised exercise."),
             ("Training & Social Interaction", "Teach simple behaviours through calm, short sessions."),
             ("Health & Grooming", "Monitor subtle signs and arrange avian veterinary care."),
         ])
    path("lovebirds", "Lovebirds", "Beginner",
         "Caring for affectionate, social lovebirds.", 35, 1, [
             ("Understanding Lovebirds", "Learn their social behaviour, personalities, and activity needs."),
             ("Preparing a Suitable Cage", "Provide safe bar spacing, perches, toys, and space."),
             ("Feeding & Nutrition", "Use formulated pellets with vegetables and limited fruit."),
             ("Bonding with Your Lovebird", "Build trust gradually through calm, voluntary interactions."),
             ("Communication & Behaviour", "Interpret chirping, posture, biting, and territorial behaviour."),
             ("Socialisation & Enrichment", "Reward calm experiences and provide climbing and foraging."),
             ("Health & Hygiene", "Clean daily and recognise illness and respiratory warning signs."),
         ])
    path("doves", "Doves", "Beginner",
         "Gentle care for calm, graceful doves.", 30, 1, [
             ("Understanding Dove Behaviour", "Recognise gentle communication, alertness, and social needs."),
             ("Preparing a Comfortable Habitat", "Provide a spacious, ventilated, predator-safe enclosure."),
             ("Feeding & Nutrition", "Use balanced seed and grain feed with clean water."),
             ("Building Trust with Doves", "Create a predictable environment and allow voluntary approach."),
             ("Social Interaction & Bonding", "Support peaceful compatible companions without forced contact."),
             ("Breeding & Nesting Care", "Provide safe nesting and monitor healthy adult birds and chicks."),
             ("Health & Hygiene", "Clean containers and housing and observe subtle illness signs."),
         ])
    path("pigeons", "Pigeons", "Beginner",
         "Keeping healthy, homing-friendly pigeons.", 35, 1, [
             ("Understanding Pigeon Behaviour", "Recognise cooing, posture, routines, and social interactions."),
             ("Preparing a Safe Loft", "Provide secure, dry, ventilated space with clean food and water."),
             ("Feeding & Nutrition", "Offer balanced grains and seeds with suitable supplements."),
             ("Building Trust with Pigeons", "Use calm, consistent interaction and routine feeding."),
             ("Flight & Exercise", "Provide safe supervised movement and never release unfamiliar pets."),
             ("Breeding & Nesting Care", "Support healthy pairs, safe nests, and responsible chick care."),
             ("Health & Hygiene", "Clean lofts and quarantine new or sick birds."),
         ])
    path("macaws", "Macaws", "Advanced",
         "Meeting the needs of a large, intelligent parrot.", 70, 2, [
             ("Understanding Macaw Behaviour", "Recognise intelligence, vocalisation, territoriality, and commitment needs."),
             ("Preparing a Macaw-Friendly Home", "Use a durable, very spacious cage and bird-safe room."),
             ("Feeding & Nutrition", "Provide formulated food with suitable vegetables and fruit."),
             ("Building Trust & Bonding", "Develop trust through calm, consistent positive interaction."),
             ("Communication & Vocalisation", "Understand calls and manage attention without reinforcing shouting."),
             ("Training & Mental Stimulation", "Use targets, foraging, and short reward-based training sessions."),
             ("Health & Grooming", "Arrange avian veterinary care and monitor weight and behaviour."),
         ])
    path("pet-first-aid", "Pet First Aid", "Beginner",
         "Handle common emergencies before you reach the vet.", 35, 1, [
             ("Understanding Pet Emergencies", "Recognise life-threatening signs and seek immediate veterinary care."),
             ("Preparing a Pet First Aid Kit", "Keep useful supplies and important medical information ready."),
             ("Wound Care & Bleeding", "Apply safe pressure and never remove embedded objects."),
             ("Choking & Breathing Emergencies", "Recognise airway emergencies and call a veterinarian."),
             ("Poisoning & Toxic Substances", "Identify suspected toxins and never induce vomiting without advice."),
             ("Fractures, Burns & Injuries", "Limit movement and cool burns safely while arranging care."),
             ("Emergency Response & Veterinary Care", "Prepare transport, records, and practical first-aid training."),
         ])
    path("paws-food-diet", "Dog Food Diet", "Intermediate",
         "Balanced nutrition for dogs and other 'paws' pets.", 50, 1, [
             ("Understanding Dog Nutritional Needs", "Provide protein, fats, carbohydrates, vitamins, minerals, and water."),
             ("Choosing the Right Dog Food", "Select complete, life-stage food suited to the individual dog."),
             ("Puppy, Adult & Senior Diets", "Adjust nutrition for growth, maintenance, ageing, and health."),
             ("Homemade Food & Balanced Meals", "Use only professionally formulated homemade plans."),
             ("Safe & Unsafe Foods for Dogs", "Avoid toxic foods and seek prompt help if poisoning occurs."),
             ("Feeding Schedules & Portion Control", "Measure meals and monitor body condition and activity."),
             ("Special Diets & Weight Management", "Use veterinary diets and gradual weight-management plans."),
         ])
    path("claws-food-diet", "Cat Food Diet", "Intermediate",
         "Feeding cats and other 'claws' companions well.", 50, 1, [
             ("Understanding Cat Nutritional Needs", "Cats require animal-based protein and essential nutrients."),
             ("Choosing the Right Cat Food", "Select complete food for life stage and health condition."),
             ("Kitten, Adult & Senior Diets", "Adjust energy and nutrient density throughout life."),
             ("Wet Food vs Dry Food", "Choose based on hydration, dental needs, and veterinary guidance."),
             ("Safe & Unsafe Foods for Cats", "Avoid toxic foods and nutritionally incomplete raw diets."),
             ("Feeding Schedules & Portion Control", "Measure meals and monitor appetite and body weight."),
             ("Special Diets & Weight Management", "Use veterinary plans for medical conditions and safe weight loss."),
         ])
    db.session.commit()


def _seed_lifestyle(owner):
    """Seed pet-friendly places and the demo adopter's expense items."""
    Place.query.delete()
    ExpenseItem.query.filter_by(owner_id=owner.id).delete()
    db.session.commit()

    # Pet-friendly places + emergency clinics around Chennai (Adyar area).
    db.session.add_all([
        Place(name="Theosophical Society Gardens", category=PlaceCategory.PARK,
              city="Chennai", address="Adyar", lat=13.0067, lng=80.2570, rating=4.6,
              note="Shaded walking trails, water bowls. Dogs on leash.", distance_km=0.8),
        Place(name="Paws & Brews Café", category=PlaceCategory.CAFE, city="Chennai",
              address="Besant Nagar", lat=13.0002, lng=80.2668, rating=4.7,
              note="Pet menu available.", distance_km=1.2),
        Place(name="Fluffy Cuts Grooming", category=PlaceCategory.GROOMING, city="Chennai",
              address="Adyar", lat=13.0089, lng=80.2550, rating=4.8,
              note="Book online.", distance_km=2.0),
        Place(name="CareVet Clinic", category=PlaceCategory.VET, city="Chennai",
              address="21 LB Road, Adyar", lat=13.0045, lng=80.2560, rating=4.9,
              note="Open till 8 PM.", distance_km=2.1),
        Place(name="Happy Tails Boarding", category=PlaceCategory.BOARDING, city="Chennai",
              address="Velachery", lat=12.9755, lng=80.2210, rating=4.5,
              note="Day & overnight stays.", distance_km=5.5),
        # 24/7 emergency clinics (feed the Emergency Vet Finder, Task 25).
        Place(name="Chennai Pet Emergency Hospital", category=PlaceCategory.VET,
              city="Chennai", address="Adyar", lat=13.0050, lng=80.2555, rating=4.7,
              note="ICU and surgery on site.", distance_km=2.4, emergency_24h=True),
        Place(name="CareVet Night Clinic", category=PlaceCategory.VET, city="Chennai",
              address="Besant Nagar", lat=13.0010, lng=80.2660, rating=4.6,
              note="Till 2 AM.", distance_km=3.1, emergency_24h=True),
        Place(name="Madras Veterinary College ER", category=PlaceCategory.VET,
              city="Chennai", address="Vepery", lat=13.0820, lng=80.2610, rating=4.5,
              note="24/7 teaching hospital.", distance_km=6.8, emergency_24h=True),
    ])

    # Default expense items for the demo adopter (mirrors the calculator mock).
    db.session.add_all([
        ExpenseItem(owner_id=owner.id, label="Food & treats", category="food",
                    amount=1800, frequency=ExpenseFrequency.MONTHLY),
        ExpenseItem(owner_id=owner.id, label="Vet visits & vaccines", category="vet",
                    amount=6000, frequency=ExpenseFrequency.YEARLY),
        ExpenseItem(owner_id=owner.id, label="Litter & grooming", category="grooming",
                    amount=700, frequency=ExpenseFrequency.MONTHLY),
        ExpenseItem(owner_id=owner.id, label="Medication", category="medication",
                    amount=300, frequency=ExpenseFrequency.MONTHLY),
        ExpenseItem(owner_id=owner.id, label="Toys & accessories", category="toys",
                    amount=2400, frequency=ExpenseFrequency.YEARLY),
        ExpenseItem(owner_id=owner.id, label="Pet insurance", category="insurance",
                    amount=3600, frequency=ExpenseFrequency.YEARLY),
    ])
    db.session.commit()


def _seed_health(owner):
    """Seed the demo adopter's owned pets with records and vaccinations."""
    from datetime import date, timedelta

    owned_pet_ids = [
        pet_id for (pet_id,) in db.session.execute(
            db.select(OwnedPet.id).filter_by(owner_id=owner.id)
        ).all()
    ]
    if owned_pet_ids:
        db.session.query(Vaccination).filter(
            Vaccination.pet_id.in_(owned_pet_ids)
        ).delete(synchronize_session=False)
        db.session.query(MedicalRecord).filter(
            MedicalRecord.pet_id.in_(owned_pet_ids)
        ).delete(synchronize_session=False)
        db.session.commit()

    OwnedPet.query.filter_by(owner_id=owner.id).delete()
    db.session.commit()

    today = date.today()

    mochi = OwnedPet(
        owner_id=owner.id, name="Mochi", species="Cat", breed="Domestic tabby",
        sex="Female", date_of_birth=date(2023, 6, 8), weight_kg=4.2,
        microchip_id="9851 2234 7781", primary_vet="Dr. Ananya Rao, CareVet",
        personality_tags=["Calm", "Affectionate", "Indoor"],
        diet_note="Fresh water available at all times. Keep treats occasional.",
        care_schedule={
            "diet_plan": [
               {"time": "07:30", "food": "Wet food", "quantity": "1 pouch"},
               {"time": "18:30", "food": "Dry food", "quantity": "Vet-guided portion"},
            ],
            "routine_plan": "10-minute play in the morning. Brush coat in the evening.",
        },
        adopted_on=date(2025, 3, 14),
    )
    snowball = OwnedPet(
        owner_id=owner.id, name="Snowball", species="Rabbit", breed="Mini lop",
        sex="Female", date_of_birth=date(2024, 8, 2), weight_kg=1.8,
        primary_vet="Dr. Vikram Iyer",
        diet_note="Unlimited grass hay and fresh water. Introduce greens gradually.",
        care_schedule={
            "diet_plan": [
               {"time": "08:00", "food": "Hay, fresh water, leafy greens", "quantity": ""},
               {"time": "19:00", "food": "Hay and pellets", "quantity": "Vet-guided portion"},
            ],
            "routine_plan": (
               "Check the litter tray in the morning and remove wilted greens. "
               "Offer supervised floor time in the evening and check appetite and droppings."
            ),
        },
        adopted_on=date(2026, 8, 2),
    )
    db.session.add_all([mochi, snowball])
    db.session.flush()

    db.session.add_all([
        MedicalRecord(pet_id=mochi.id, record_type=RecordType.LAB,
                      title="Complete blood panel", record_date=today - timedelta(days=16),
                      vet_name="Dr. Rao",
                      summary="All values within normal range. Haemoglobin 12.1 g/dL.",
                      diagnosis="Healthy. Recheck in 12 months."),
        MedicalRecord(pet_id=mochi.id, record_type=RecordType.PRESCRIPTION,
                      title="Deworming prescription", record_date=today - timedelta(days=16),
                      vet_name="Dr. Rao", summary="Deworming tablet, monthly."),
        MedicalRecord(pet_id=mochi.id, record_type=RecordType.IMAGING,
                      title="Chest X-ray", record_date=today - timedelta(days=120),
                      vet_name="Dr. Iyer", summary="Chest clear."),
        MedicalRecord(pet_id=mochi.id, record_type=RecordType.SURGERY,
                      title="Spay surgery report", record_date=date(2025, 2, 2),
                      vet_name="Happy Paws vet", summary="Routine spay, recovered well."),
    ])

    db.session.add_all([
        Vaccination(pet_id=mochi.id, name="Rabies", kind="Core vaccine", schedule="yearly",
                    last_given=today - timedelta(days=350), due_on=today + timedelta(days=16),
                    batch="RB-1180"),
        Vaccination(pet_id=mochi.id, name="FVRCP (core)", kind="Core vaccine",
                    schedule="every 3 yrs", last_given=date(2026, 3, 10),
                    due_on=date(2029, 3, 10)),
        Vaccination(pet_id=mochi.id, name="FeLV", kind="Non-core", schedule="yearly",
                    last_given=date(2026, 1, 20), due_on=today + timedelta(days=120)),
        Vaccination(pet_id=mochi.id, name="Deworming", schedule="every 3 months",
                    last_given=today - timedelta(days=16), due_on=today + timedelta(days=75)),
        Vaccination(pet_id=snowball.id, name="Myxomatosis", kind="Core", schedule="yearly",
                    last_given=today - timedelta(days=200), due_on=today + timedelta(days=165)),
    ])
    db.session.commit()


def _seed_vets(ananya, vikram, sneha):
    """Seed vet profiles mirroring the directory mock."""
    VetProfile.query.delete()
    db.session.commit()
    db.session.add_all([
        VetProfile(
            user_id=ananya.id, display_name="Dr. Ananya Rao", slug="ananya-rao",
            qualifications="BVSc, MVSc (Medicine)", clinic_name="CareVet Clinic",
            clinic_address="21 LB Road, Adyar", city="Chennai",
            licence_no="VCI-TN-11204", experience_years=12,
            bio="Dr. Rao specialises in feline medicine and preventive care. She is "
            "known for gentle, fear-free handling and clear explanations for "
            "first-time pet parents.",
            specialties=["General", "Cats", "Vaccination"],
            languages=["Tamil", "English", "Hindi"],
            consult_fee=500, video_fee=350, rating=4.9, reviews_count=312,
            pets_treated=3400, distance_km=2.1, is_verified=True,
            offers_video=True, offers_emergency=True,
        ),
        VetProfile(
            user_id=vikram.id, display_name="Dr. Vikram Iyer", slug="vikram-iyer",
            qualifications="BVSc & AH", clinic_name="PetCare Plus",
            clinic_address="PetCare Plus, Anna Nagar", city="Chennai",
            licence_no="VCI-TN-18842", experience_years=9,
            bio="Dermatology and general practice with a focus on dogs.",
            specialties=["Dermatology", "Dogs", "General"],
            languages=["Tamil", "English"],
            consult_fee=600, video_fee=400, rating=4.8, reviews_count=204,
            pets_treated=2100, distance_km=3.4, is_verified=True, offers_video=True,
        ),
        VetProfile(
            user_id=sneha.id, display_name="Dr. Sneha Menon", slug="sneha-menon",
            qualifications="MVSc Surgery", clinic_name="Happy Tails Vet",
            clinic_address="Happy Tails Vet, Kochi", city="Kochi",
            licence_no="VCI-KL-20931", experience_years=6,
            bio="Surgery and orthopedics specialist.",
            specialties=["Surgery", "Orthopedics"],
            languages=["Malayalam", "English"],
            consult_fee=700, video_fee=0, rating=4.9, reviews_count=148,
            pets_treated=1200, distance_km=5.0, is_verified=True, offers_video=False,
        ),
    ])
    db.session.commit()


def _seed_content():
    """Seed editorial content: blog posts, success stories, and FAQs."""
    BlogPost.query.delete()
    SuccessStory.query.delete()
    FAQ.query.delete()
    db.session.commit()

    db.session.add_all([
        BlogPost(
            slug="first-30-days-rescue-dog",
            title="Your first 30 days with a rescue dog",
            category="Adoption",
            author="Dr. Ananya Rao",
            read_minutes=8,
            cover_url=_u("blog_adoption"),
            excerpt="A week-by-week guide to settling in, building trust, and creating routines.",
            body=(
                "Week one: decompress. Give your new friend a quiet corner, a "
                "predictable schedule, and lots of patience. Many rescues need a "
                "few days just to feel safe, so keep visitors and loud noises to a "
                "minimum and let them explore at their own pace.\n\n"
                "Week two: build routines. Feed, walk, and rest at consistent times. "
                "Predictability lowers anxiety and helps your dog understand that "
                "this is their forever home. Start short, positive training sessions.\n\n"
                "Week three: first outings. Introduce new places gradually and keep "
                "walks calm. Reward curiosity and never force an interaction. Watch "
                "body language for signs of stress.\n\n"
                "Week four: training basics. Reinforce name recognition, recall, and "
                "gentle leash manners with treats and praise. By now trust is "
                "forming, and your rescue is settling into the rhythm of family life."
            ),
        ),
        BlogPost(
            slug="vaccination-schedule-kittens",
            title="Vaccination schedule for kittens",
            category="Health",
            author="Dr. Ananya Rao",
            read_minutes=5,
            cover_url=_u("blog_health"),
            excerpt="What shots your kitten needs and when.",
            body=(
                "Kittens need a series of core vaccines starting at 6 to 8 weeks of "
                "age. The core FVRCP vaccine protects against three common and "
                "serious feline viruses, and is usually given in two to three doses "
                "a few weeks apart.\n\n"
                "Rabies is typically given once around 12 to 16 weeks, and is "
                "required by law in many places. Non-core vaccines like FeLV may be "
                "recommended depending on your kitten's lifestyle.\n\n"
                "Always keep a record of dates and bring it to every vet visit. Your "
                "vet will tailor the schedule to your kitten's health and risk."
            ),
        ),
        BlogPost(
            slug="reading-pet-food-labels",
            title="Reading pet food labels",
            category="Nutrition",
            author="PetShip Team",
            read_minutes=4,
            cover_url=_u("blog_nutrition"),
            excerpt="Decode ingredient lists and pick better food.",
            body=(
                "The first ingredients matter most, because they make up the bulk of "
                "the food. Look for a named protein source such as chicken or lamb at "
                "the top of the list, rather than vague terms like meat by-product.\n\n"
                "Check for a statement of nutritional adequacy from a recognised "
                "authority, which tells you the food is complete and balanced for "
                "your pet's life stage.\n\n"
                "Treats should make up no more than ten percent of daily calories. "
                "When in doubt, ask your vet for a recommendation suited to your "
                "pet's age, weight, and activity."
            ),
        ),
        BlogPost(
            slug="leash-training-without-stress",
            title="Leash training without stress",
            category="Training",
            author="PetShip Team",
            read_minutes=6,
            cover_url=_u("blog_training"),
            excerpt="Gentle steps to a happy walk.",
            body=(
                "Start indoors where there are few distractions. Let your dog wear "
                "the harness and leash around the house so it feels normal before you "
                "ever step outside.\n\n"
                "Reward often. Every time your dog walks beside you with a loose "
                "leash, mark it with praise or a treat. Keep sessions short and "
                "upbeat, ending before your dog gets bored or frustrated.\n\n"
                "If your dog pulls, stop walking and wait. Moving forward only when "
                "the leash is slack teaches that pulling never gets them anywhere."
            ),
        ),
        BlogPost(
            slug="is-a-rabbit-right-for-you",
            title="Is a rabbit right for you?",
            category="Care",
            author="PetShip Team",
            read_minutes=7,
            cover_url=_u("blog_care"),
            excerpt="What to know before adopting a bunny.",
            body=(
                "Rabbits are quiet, clean, and affectionate companions, but they are "
                "a bigger commitment than many people expect. They can live eight to "
                "twelve years and need daily care and space to move.\n\n"
                "A good diet is mostly hay, with fresh greens and a small amount of "
                "pellets. Rabbits also need companionship and enrichment, and often do "
                "best in bonded pairs.\n\n"
                "Rabbit-proof your home, since they love to chew. If you can offer "
                "space, routine, and gentle handling, a rabbit makes a wonderful and "
                "rewarding pet."
            ),
        ),
    ])

    db.session.add_all([
        SuccessStory(
            title="We came for one shy pup and left with a best friend",
            family="The Kumar family & Biscuit",
            pet_name="Biscuit",
            quote="We came for one shy pup and left with a best friend who changed our whole family.",
            body="Adopted from Happy Paws in March 2026.",
            photo_url=_u("biscuit"),
            featured=True,
        ),
        SuccessStory(
            title="She owns the windowsill now",
            family="Priya & Mochi",
            pet_name="Mochi",
            quote="She owns the windowsill now, and my heart too.",
            photo_url=_u("mochi"),
        ),
        SuccessStory(
            title="My running buddy",
            family="Arjun & Max",
            pet_name="Max",
            quote="My running buddy and the best listener I know.",
            photo_url=_u("storymax"),
        ),
        SuccessStory(
            title="A tiny rabbit with a huge personality",
            family="Lakshmi & Snow",
            pet_name="Snow",
            quote="A tiny rabbit with a huge personality.",
            photo_url=_u("snow"),
        ),
    ])

    faqs = [
        ("Adoption", "How does the adoption process work?",
         "Browse pets, submit an application, and the shelter reviews it. Then there's "
         "a home visit, you sign a digital agreement, and you welcome your pet home.", 1),
        ("Adoption", "Are there adoption fees?",
         "Most shelters charge a fee that covers vaccinations, neutering, and microchipping.", 2),
        ("Adoption", "How are shelters verified?",
         "Our team reviews registration documents and facility details before approval.", 3),
        ("Adoption", "Can I return a pet if it doesn't work out?",
         "Shelters have return policies to ensure every pet stays safe. Talk to the shelter.", 4),
        ("Adoption", "How accurate is AI matching?",
         "Our matching scores lifestyle and space fit. It's a strong guide, not a guarantee.", 5),
        ("Account & login", "How do I reset my password?",
         "Use the 'Forgot password' link on the login screen to receive a reset email.", 1),
        ("Vet appointments", "Can I book a video consult?",
         "Yes, many vets offer video consults. Choose it when booking.", 1),
        ("Health records", "Who can see my pet's records?",
         "Only you and the vets you choose. You control sharing from the pet's profile.", 1),
        ("For shelters", "How do I list a pet?",
         "Once verified, use the Add New Pet screen in your shelter dashboard.", 1),
        ("Payments", "Is my payment information secure?",
         "Payments are processed securely and we never store card details.", 1),
    ]
    db.session.add_all(
        FAQ(category=c, question=q, answer=a, sort_order=o) for c, q, a, o in faqs
    )
    db.session.commit()


@click.command("seed")
@with_appcontext
def seed_command():
    """Load demo shelters, users, and pets."""
    summary = seed_data()
    click.echo(
        f"Seeded: {summary['users']} users, {summary['shelters']} shelters, "
        f"{summary['pets']} pets ({summary['available']} available), "
        f"{summary['blog']} blog posts, {summary['stories']} stories, "
        f"{summary['faqs']} FAQs, {summary['vets']} vets."
    )


def register_seed(app: Flask) -> None:
    app.cli.add_command(seed_command)
